import { InternalLogsVerifier, signInternalLogs } from './internal-logs'

const KEY = 'internal-logs-test-key'
const OTHER_KEY = 'internal-logs-other-key'
const TEAM_ID = 2
const OTHER_TEAM_ID = 3
const PAYLOAD = Buffer.from('avro container bytes')

describe('InternalLogsVerifier', () => {
    it.each([
        { name: 'accepts a batch signed with the newest key', signature: signInternalLogs(KEY, TEAM_ID, PAYLOAD) },
        {
            name: 'accepts a batch signed with an older key during rotation',
            keys: `${OTHER_KEY},${KEY}`,
            signature: signInternalLogs(KEY, TEAM_ID, PAYLOAD),
        },
    ])('$name', ({ signature, keys = KEY }) => {
        expect(new InternalLogsVerifier(keys, String(TEAM_ID)).isInternal(signature, TEAM_ID, PAYLOAD)).toBe(true)
    })

    it.each([
        { name: 'no header', signature: undefined },
        { name: 'a malformed signature', signature: 'v1.not-a-signature' },
        { name: 'an unknown key', signature: signInternalLogs(OTHER_KEY, TEAM_ID, PAYLOAD) },
        { name: "another team's signature", signature: signInternalLogs(KEY, OTHER_TEAM_ID, PAYLOAD) },
        { name: 'a signature over different data', signature: signInternalLogs(KEY, TEAM_ID, Buffer.from('other')) },
        {
            name: 'a team not on the allowlist',
            teams: String(OTHER_TEAM_ID),
            signature: signInternalLogs(KEY, TEAM_ID, PAYLOAD),
        },
        { name: 'a wildcard allowlist', teams: '*', signature: signInternalLogs(KEY, TEAM_ID, PAYLOAD) },
        { name: 'no configured key', keys: '', signature: signInternalLogs(KEY, TEAM_ID, PAYLOAD) },
        { name: 'an empty payload', payload: null, signature: signInternalLogs(KEY, TEAM_ID, PAYLOAD) },
    ])(
        'bills a batch with $name',
        ({ signature, keys = KEY, teams = String(TEAM_ID), payload = PAYLOAD as Buffer | null }) => {
            expect(new InternalLogsVerifier(keys, teams).isInternal(signature, TEAM_ID, payload)).toBe(false)
        }
    )

    // Producers and consumers deploy separately, so a format change must be a new version prefix.
    it('keeps the v1 signature format stable', () => {
        expect(signInternalLogs(KEY, TEAM_ID, PAYLOAD)).toEqual(
            'v1.37622e648ef9cdbc738af454a15f2e93297f2d383ae1a6f6319b2c183a77080e'
        )
    })
})
