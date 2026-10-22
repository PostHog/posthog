import { InternalLogsVerifier, signInternalLogs } from './internal-logs'

const KEY = 'internal-logs-test-key'
const OTHER_KEY = 'internal-logs-other-key'
const SOURCE = 'hog_flow'
const TEAM_ID = 2
const OTHER_TEAM_ID = 3
const PAYLOAD = Buffer.from('avro container bytes')

describe('InternalLogsVerifier', () => {
    it.each([
        {
            name: 'accepts a batch signed with the newest key',
            signature: signInternalLogs(KEY, SOURCE, TEAM_ID, PAYLOAD),
        },
        {
            name: 'accepts a batch signed with an older key during rotation',
            keys: `${OTHER_KEY},${KEY}`,
            signature: signInternalLogs(KEY, SOURCE, TEAM_ID, PAYLOAD),
        },
        {
            name: 'accepts a batch on a wildcard allowlist',
            teams: '*',
            signature: signInternalLogs(KEY, SOURCE, TEAM_ID, PAYLOAD),
        },
    ])('$name', ({ signature, keys = KEY, teams = String(TEAM_ID) }) => {
        expect(new InternalLogsVerifier(keys, teams).verify(signature, TEAM_ID, PAYLOAD)).toEqual({
            source: SOURCE,
            billed: false,
            teamRules: false,
        })
    })

    it.each([
        { name: 'no header', signature: undefined },
        { name: 'a malformed signature', signature: 'v1.not-a-signature' },
        { name: 'an unknown key', signature: signInternalLogs(OTHER_KEY, SOURCE, TEAM_ID, PAYLOAD) },
        { name: "another team's signature", signature: signInternalLogs(KEY, SOURCE, OTHER_TEAM_ID, PAYLOAD) },
        {
            name: 'a signature moved to another source',
            signature: signInternalLogs(KEY, SOURCE, TEAM_ID, PAYLOAD).replace(`.${SOURCE}.`, '.hog_function.'),
        },
        {
            name: 'a signature over different data',
            signature: signInternalLogs(KEY, SOURCE, TEAM_ID, Buffer.from('other')),
        },
        {
            name: 'a team not on the allowlist',
            teams: String(OTHER_TEAM_ID),
            signature: signInternalLogs(KEY, SOURCE, TEAM_ID, PAYLOAD),
        },
        { name: 'no configured key', keys: '', signature: signInternalLogs(KEY, SOURCE, TEAM_ID, PAYLOAD) },
        { name: 'a source with no policy', signature: signInternalLogs(KEY, 'not_a_source', TEAM_ID, PAYLOAD) },
        { name: 'an inherited property as source', signature: signInternalLogs(KEY, 'constructor', TEAM_ID, PAYLOAD) },
        { name: 'the prototype as source', signature: signInternalLogs(KEY, '__proto__', TEAM_ID, PAYLOAD) },
        { name: 'an empty payload', payload: null, signature: signInternalLogs(KEY, SOURCE, TEAM_ID, PAYLOAD) },
    ])(
        'bills a batch with $name',
        ({ signature, keys = KEY, teams = String(TEAM_ID), payload = PAYLOAD as Buffer | null }) => {
            expect(new InternalLogsVerifier(keys, teams).verify(signature, TEAM_ID, payload)).toBeUndefined()
        }
    )

    it('refuses to sign a source that cannot go into the header', () => {
        expect(() => signInternalLogs(KEY, 'hog.flow', TEAM_ID, PAYLOAD)).toThrow('invalid source')
    })

    // Producers and consumers deploy separately, so a format change must be a new version prefix.
    it('keeps the v1 signature format stable', () => {
        expect(signInternalLogs(KEY, SOURCE, TEAM_ID, PAYLOAD)).toEqual(
            'v1.hog_flow.b97466e15a9bf1a2658e8d92e5f63ed60df91bd4e838e4ab4426cbb5280d2055'
        )
    })
})
