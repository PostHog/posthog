import { EventEmitter } from 'events'
import { PoolClient } from 'pg'

import { PostgresRouter } from '~/common/utils/db/postgres'

import {
    PreferenceStatus,
    RecipientManagerRecipient,
    RecipientsManagerService,
} from '../../managers/recipients-manager.service'
import { FrequencyCapCheck } from '../recipient-preferences.service'
import { AUTHORIZATION_TIMEOUT_MS, SandboxAuthorization } from './sandbox-authorization'
import {
    SandboxEmailService,
    SandboxEmailServiceDeps,
    SandboxSendOutcome,
    SandboxSendRequest,
    hasSandboxSenderRow,
} from './sandbox-email.service'
import { checkSandboxRecipient } from './sandbox-recipient-checks'

describe('SandboxEmailService', () => {
    const now = new Date('2026-01-01T12:00:00.000Z')
    const member: SandboxAuthorization = {
        ok: true,
        organizationId: 'org-1',
        organizationName: 'Acme',
        storedAddress: 'Member@Example.com',
        tenant: { sendingStatus: 'ENABLED', syncedAt: new Date(now.getTime() - 60_000) },
    }

    const fakeDeps = (overrides: Partial<SandboxEmailServiceDeps> = {}): jest.Mocked<SandboxEmailServiceDeps> =>
        ({
            enabled: true,
            fromAddress: 'sandbox@send.example.com',
            tenantName: 'sandbox-tenant',
            isProvisioned: jest.fn().mockResolvedValue(true),
            authorize: jest.fn().mockResolvedValue(member),
            checkRecipient: jest.fn().mockResolvedValue({ ok: true }),
            claimCaps: jest.fn().mockResolvedValue({ ok: true }),
            ses: { send: jest.fn().mockResolvedValue({ status: 'accepted', messageId: 'ses-1' }) },
            now: () => now,
            ...overrides,
        }) as jest.Mocked<SandboxEmailServiceDeps>

    const request = (overrides: Partial<SandboxSendRequest> = {}): SandboxSendRequest => ({
        teamId: 2,
        hogFlowId: 'flow-1',
        invocationId: 'run-1',
        actionId: 'action_email_sandbox_1',
        flowVersion: 4,
        isTest: false,
        email: { to: { email: 'member@example.com', name: 'Mem' }, subject: 'Hi', text: 'Hello' },
        ...overrides,
    })

    it('sends one message to the stored member spelling, from the organization, with the run tags', async () => {
        const deps = fakeDeps()

        await expect(new SandboxEmailService(deps).send(request())).resolves.toEqual({
            status: 'accepted',
            messageId: 'ses-1',
        })

        expect(deps.authorize).toHaveBeenCalledWith({
            teamId: 2,
            recipient: 'member@example.com',
            tenantName: 'sandbox-tenant',
        })
        expect(deps.claimCaps).toHaveBeenCalledWith({
            organizationId: 'org-1',
            teamId: 2,
            storedAddress: 'Member@Example.com',
        })
        expect(deps.ses.send).toHaveBeenCalledTimes(1)
        const [message, tags] = jest.mocked(deps.ses.send).mock.calls[0]
        expect(message).toMatchObject({
            from: { address: 'sandbox@send.example.com', name: 'Acme via PostHog' },
            to: { address: 'Member@Example.com', name: 'Mem' },
            subject: 'Hi',
        })
        expect(tags).toMatchObject({
            teamId: 2,
            hogFlowId: 'flow-1',
            invocationId: 'run-1',
            actionId: 'action_email_sandbox_1',
            flowVersion: 4,
            isTest: false,
        })
    })

    const stale = { sendingStatus: 'ENABLED', syncedAt: new Date(now.getTime() - 600_000) }
    const paused = { sendingStatus: 'DISABLED', syncedAt: now }

    it.each<[string, Partial<SandboxEmailServiceDeps>, Partial<SandboxSendRequest>, string, string]>([
        ['the kill switch is off', { enabled: false }, {}, 'skipped', 'sending_disabled'],
        [
            'the payload has no subject',
            {},
            { email: { to: { email: 'a@b.co' }, text: 'x' } },
            'failed',
            'render_failed',
        ],
        [
            'the action id has a character SES tags cannot carry',
            {},
            { actionId: 'email.step' },
            'failed',
            'unsupported_action_id',
        ],
        [
            'the team has no sandbox sender',
            { isProvisioned: jest.fn().mockResolvedValue(false) },
            {},
            'skipped',
            'sandbox_not_provisioned',
        ],
        [
            'the provisioning read fails',
            { isProvisioned: jest.fn().mockRejectedValue(new Error('db down')) },
            {},
            'retry',
            'authorization_unavailable',
        ],
        ...[
            'a@example.com, b@example.com',
            '"Boss" <a@example.com>',
            'a@example.com\r\nBcc: b@example.com',
            'not-an-address',
        ].map((to): [string, Partial<SandboxEmailServiceDeps>, Partial<SandboxSendRequest>, string, string] => [
            `the recipient is ${JSON.stringify(to)}`,
            {},
            { email: { to: { email: to }, subject: 'Hi', text: 'x' } },
            'skipped',
            'invalid_recipient',
        ]),
        [
            'the recipient is suppressed',
            { checkRecipient: jest.fn().mockResolvedValue({ ok: false, reason: 'suppressed' }) },
            {},
            'skipped',
            'suppressed',
        ],
        [
            'the suppression read fails',
            { checkRecipient: jest.fn().mockResolvedValue({ ok: false, reason: 'authorization_unavailable' }) },
            {},
            'retry',
            'authorization_unavailable',
        ],
        [
            'the recipient is not a member',
            { authorize: jest.fn().mockResolvedValue({ ok: false, reason: 'not_member' }) },
            {},
            'skipped',
            'not_member',
        ],
        [
            'the organization is blocked',
            { authorize: jest.fn().mockResolvedValue({ ok: false, reason: 'organization_blocked' }) },
            {},
            'skipped',
            'organization_blocked',
        ],
        [
            'the member read fails',
            { authorize: jest.fn().mockResolvedValue({ ok: false, reason: 'authorization_unavailable' }) },
            {},
            'retry',
            'authorization_unavailable',
        ],
        [
            'the tenant mirror is stale',
            { authorize: jest.fn().mockResolvedValue({ ...member, tenant: stale }) },
            {},
            'retry',
            'pause_state_unavailable',
        ],
        [
            'the tenant is paused',
            { authorize: jest.fn().mockResolvedValue({ ...member, tenant: paused }) },
            {},
            'skipped',
            'tenant_paused',
        ],
        [
            'a daily cap is reached',
            { claimCaps: jest.fn().mockResolvedValue({ ok: false, reason: 'daily_cap_reached' }) },
            {},
            'skipped',
            'daily_cap_reached',
        ],
        [
            'the cap storage fails',
            { claimCaps: jest.fn().mockResolvedValue({ ok: false, reason: 'cap_storage_unavailable' }) },
            {},
            'retry',
            'cap_storage_unavailable',
        ],
    ])('sends nothing when %s', async (_name, overrides, requestOverrides, status, reason) => {
        const deps = fakeDeps(overrides)

        await expect(new SandboxEmailService(deps).send(request(requestOverrides))).resolves.toEqual({
            status,
            reason,
        })
        expect(deps.ses.send).not.toHaveBeenCalled()
    })

    it('claims no cap when a recipient check refuses the send', async () => {
        const deps = fakeDeps({ checkRecipient: jest.fn().mockResolvedValue({ ok: false, reason: 'opted_out' }) })

        await new SandboxEmailService(deps).send(request())

        expect(deps.authorize).not.toHaveBeenCalled()
        expect(deps.claimCaps).not.toHaveBeenCalled()
    })

    const withRecipientChecks = (preferencesByIdentifier: Record<string, Record<string, PreferenceStatus>> = {}) => {
        const recipients = new RecipientsManagerService({} as PostgresRouter)
        jest.spyOn(recipients, 'get').mockImplementation(({ identifier }) => {
            const preferences = preferencesByIdentifier[identifier]
            const recipient: RecipientManagerRecipient | null = preferences
                ? { id: 'recipient', team_id: 2, identifier, preferences, created_at: '', updated_at: '' }
                : null
            return Promise.resolve(recipient)
        })
        return fakeDeps({
            checkRecipient: (check) =>
                checkSandboxRecipient(
                    { suppression: { isSuppressed: () => Promise.resolve(false) }, recipients },
                    check
                ),
        })
    }

    it.each([
        ['the trimmed address', 'member@example.com'],
        ['the padded address its unsubscribe link carried', ' member@example.com '],
        ['the stored member spelling', 'Member@Example.com'],
    ])('refuses a padded recipient who opted out under %s', async (_name, optedOutIdentifier) => {
        const deps = withRecipientChecks({ [optedOutIdentifier]: { news: 'OPTED_OUT' } })

        await expect(
            new SandboxEmailService(deps).send(
                request({
                    email: { to: { email: ' member@example.com ' }, subject: 'Hi', text: 'Hello' },
                    categoryId: 'news',
                    categoryType: 'marketing',
                    frequencyCap: () => Promise.resolve({ capped: false }),
                })
            )
        ).resolves.toEqual({ status: 'skipped', reason: 'opted_out' })
        expect(deps.ses.send).not.toHaveBeenCalled()
        expect(deps.claimCaps).not.toHaveBeenCalled()
    })

    it('reuses a cap claim held after an SES throttle only for the recipient it was claimed for', async () => {
        const deps = fakeDeps({
            ses: { send: jest.fn().mockResolvedValue({ status: 'retry', reason: 'ses_throttled' }) },
        })
        const service = new SandboxEmailService(deps)

        const throttled = await service.send(request())
        expect(throttled).toEqual({ status: 'retry', reason: 'ses_throttled', capsClaimedFor: expect.any(String) })
        const capsClaimedFor = (throttled as { capsClaimedFor: string }).capsClaimedFor

        await service.send(request({ capsClaimedFor }))
        expect(deps.claimCaps).toHaveBeenCalledTimes(1)

        deps.authorize.mockResolvedValue({ ...member, storedAddress: 'other@example.com' })
        await service.send(
            request({ capsClaimedFor, email: { to: { email: 'other@example.com' }, subject: 'Hi', text: 'Hello' } })
        )
        expect(deps.claimCaps).toHaveBeenCalledTimes(2)
    })

    const capped = (): Promise<FrequencyCapCheck> =>
        Promise.resolve({ capped: true, nextSlotAt: now.getTime() + 3_600_000, holdHours: null })
    const accepted: SandboxSendOutcome = { status: 'accepted', messageId: 'ses-1' }
    const optedOut: SandboxSendOutcome = { status: 'skipped', reason: 'opted_out' }

    it.each<[string, Partial<SandboxSendRequest>, SandboxSendOutcome]>([
        [
            'a run opt-out from its category',
            { optOuts: [{ identifier: 'member@example.com', categoryId: 'news' }] },
            optedOut,
        ],
        [
            'a run opt-out from all marketing',
            { optOuts: [{ identifier: 'member@example.com', categoryId: '$all' }] },
            optedOut,
        ],
        [
            'a run opt-out from another category',
            { optOuts: [{ identifier: 'member@example.com', categoryId: 'other' }] },
            accepted,
        ],
        ['a reached frequency cap', { frequencyCap: capped }, { status: 'skipped', reason: 'frequency_capped' }],
        ['a reached frequency cap on a test send', { frequencyCap: capped, isTest: true }, accepted],
    ])('applies %s to a marketing send', async (_case, overrides, outcome) => {
        const deps = withRecipientChecks()

        await expect(
            new SandboxEmailService(deps).send(request({ categoryId: 'news', categoryType: 'marketing', ...overrides }))
        ).resolves.toEqual(outcome)
        expect(deps.ses.send).toHaveBeenCalledTimes(outcome.status === 'accepted' ? 1 : 0)
    })

    it('gives up on a provisioning read the database never answers, and destroys that connection', async () => {
        jest.useFakeTimers()
        try {
            const router = new PostgresRouter({ DATABASE_URL: 'postgres://fake', POSTGRES_CONNECTION_POOL_SIZE: 1 })
            const stalled = Object.assign(new EventEmitter(), {
                query: jest.fn(() => new Promise<never>(() => undefined)),
                release: jest.fn(),
            })
            jest.spyOn(router, 'connect').mockResolvedValue(stalled as unknown as PoolClient)

            const read = hasSandboxSenderRow(router, 1).catch((error: Error) => error)
            await jest.advanceTimersByTimeAsync(AUTHORIZATION_TIMEOUT_MS)

            expect(await read).toEqual(expect.objectContaining({ message: expect.stringContaining('deadline') }))
            expect(stalled.release).toHaveBeenCalledWith(expect.any(Error))
        } finally {
            jest.useRealTimers()
        }
    })
})
