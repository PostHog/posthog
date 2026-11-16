import { PostgresRouter } from '~/common/utils/db/postgres'

import { EncryptedFields } from '../cdp/utils/encryption-utils'
import { LogsSigningSecretsCache, signLogs, verifyLogsSignature, withSignatureStatus } from './log-signature'

const TEAM_ID = 2
const SIGNED_AT = new Date('2026-10-27T12:00:00Z')
const CREATED_AT = '2026-10-27T12:01:00.123456789+00:00'

// Python `Fernet` wrote these with the key below, as Django's `EncryptedTextField` does.
const ENCRYPTION_KEY = '00beef0000beef0000beef0000beef00'
const CURRENT_TOKEN =
    'gAAAAABlU_EAAAECAwQFBgcICQoLDA0OD6wHltQjGRg-WTHwev-y3BTmMdfqPYo0iHd59v-WC8clhUo6Hkcz3sFBbnRR_hR-Lg=='
const PREVIOUS_TOKEN =
    'gAAAAABlU_EAEBESExQVFhcYGRobHB0eH_hdmiV6kFgJdUlyDrGrhVQKTBT63y_OZKADkMD0pyEY3NOZAtO2Gzzv5xcg9ttDaA=='

describe('logs signature', () => {
    afterEach(() => jest.restoreAllMocks())

    const source = (secrets: string[]) => ({ getSecrets: () => Promise.resolve(secrets) })

    it.each([
        { name: 'the current secret', secrets: ['current'], signature: signLogs('current', TEAM_ID, SIGNED_AT) },
        {
            name: 'the previous secret in its grace period',
            secrets: ['current', 'previous'],
            signature: signLogs('previous', TEAM_ID, SIGNED_AT),
        },
        {
            name: 'a customer clock that runs ahead of capture',
            secrets: ['current'],
            signature: signLogs('current', TEAM_ID, SIGNED_AT),
            createdAt: '2026-10-27T11:56:00Z',
        },
    ])('verifies a batch signed with $name', async ({ secrets, signature, createdAt = CREATED_AT }) => {
        expect(await verifyLogsSignature(source(secrets), signature, TEAM_ID, createdAt)).toBe(true)
    })

    it.each([
        { name: 'no header', signature: undefined },
        { name: 'a team with no secret', secrets: [] as string[], signature: signLogs('current', TEAM_ID, SIGNED_AT) },
        { name: 'another secret', signature: signLogs('other', TEAM_ID, SIGNED_AT) },
        { name: "another team's signature", signature: signLogs('current', TEAM_ID + 1, SIGNED_AT) },
        {
            name: 'a signature outside the window',
            signature: signLogs('current', TEAM_ID, SIGNED_AT),
            createdAt: '2026-10-27T12:06:00Z',
        },
        { name: 'a missing created_at', signature: signLogs('current', TEAM_ID, SIGNED_AT), createdAt: null },
        { name: 'a malformed value', signature: 'v1.not-a-time.abc' },
    ])('does not verify $name', async ({ secrets = ['current'], signature, createdAt = CREATED_AT }) => {
        expect(await verifyLogsSignature(source(secrets), signature, TEAM_ID, createdAt ?? undefined)).toBe(false)
    })

    it('removes incoming signature headers and sets the status only for a verified batch', () => {
        const incoming = { 'posthog-signature': 'v1.x.y', 'signature-status': 'verified', token: 't' }
        expect(withSignatureStatus(incoming, false)).toEqual({ token: 't' })
        expect(withSignatureStatus(incoming, true)).toEqual({ token: 't', 'signature-status': 'verified' })
    })

    describe('LogsSigningSecretsCache', () => {
        let query: jest.Mock
        let cache: LogsSigningSecretsCache
        const NOW = new Date('2026-10-27T12:00:00Z').getTime()
        const row = (rotatedHoursAgo: number | null) => ({
            secret: CURRENT_TOKEN,
            previous_secret: rotatedHoursAgo === null ? null : PREVIOUS_TOKEN,
            previous_secret_rotated_at: rotatedHoursAgo === null ? null : new Date(NOW - rotatedHoursAgo * 3_600_000),
        })

        beforeEach(() => {
            query = jest.fn()
            cache = new LogsSigningSecretsCache(
                { query } as unknown as PostgresRouter,
                new EncryptedFields(ENCRYPTION_KEY)
            )
            jest.spyOn(Date, 'now').mockReturnValue(NOW)
        })

        it.each([
            ['no secrets for a team without a row', [], []],
            ['the decrypted current secret', [row(null)], ['current-secret']],
            ['the previous secret inside the grace period', [row(47)], ['current-secret', 'previous-secret']],
            ['only the current secret after the grace period', [row(49)], ['current-secret']],
            ['no secret that the configured keys cannot decrypt', [{ ...row(null), secret: 'gAAAAAnot-ours' }], []],
        ])('serves %s', async (_, rows, expected) => {
            query.mockResolvedValueOnce({ rows })
            expect(await cache.getSecrets(TEAM_ID)).toEqual(expected)
        })

        it('serves no secrets when the first fetch fails, then the last-known ones on a later failure', async () => {
            query.mockRejectedValueOnce(new Error('pg down'))
            expect(await cache.getSecrets(TEAM_ID)).toEqual([])

            jest.spyOn(Date, 'now').mockReturnValue(NOW + 6_000)
            query.mockResolvedValueOnce({ rows: [row(null)] })
            expect(await cache.getSecrets(TEAM_ID)).toEqual(['current-secret'])

            jest.spyOn(Date, 'now').mockReturnValue(NOW + 60_000)
            query.mockRejectedValueOnce(new Error('pg down'))
            expect(await cache.getSecrets(TEAM_ID)).toEqual(['current-secret'])
            expect(query).toHaveBeenCalledTimes(3)
        })
    })
})
