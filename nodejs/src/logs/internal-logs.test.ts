import { InternalLogsVerifier, signInternalLogs } from './internal-logs'

const KEY = 'internal-logs-test-key'
const OTHER_KEY = 'internal-logs-other-key'
const SOURCE = 'hog_flow'
const TEAM_ID = 2
const OTHER_TEAM_ID = 3

describe('InternalLogsVerifier', () => {
    it.each([
        {
            name: 'accepts a batch signed with the newest key',
            signature: signInternalLogs(KEY, SOURCE, TEAM_ID),
        },
        {
            name: 'accepts a batch signed with an older key during rotation',
            keys: `${OTHER_KEY},${KEY}`,
            signature: signInternalLogs(KEY, SOURCE, TEAM_ID),
        },
        {
            name: 'accepts a batch on a wildcard allowlist',
            teams: '*',
            signature: signInternalLogs(KEY, SOURCE, TEAM_ID),
        },
    ])('$name', ({ signature, keys = KEY, teams = String(TEAM_ID) }) => {
        expect(new InternalLogsVerifier(keys, teams).verify(signature, TEAM_ID)).toEqual({
            source: SOURCE,
            billed: false,
            teamRules: false,
        })
    })

    it.each([
        { name: 'no header', signature: undefined },
        { name: 'a malformed signature', signature: 'v1.not-a-signature' },
        { name: 'an unknown key', signature: signInternalLogs(OTHER_KEY, SOURCE, TEAM_ID) },
        { name: "another team's signature", signature: signInternalLogs(KEY, SOURCE, OTHER_TEAM_ID) },
        {
            name: 'a signature moved to another source',
            signature: signInternalLogs(KEY, SOURCE, TEAM_ID).replace(`.${SOURCE}.`, '.hog_function.'),
        },
        {
            name: 'a team not on the allowlist',
            teams: String(OTHER_TEAM_ID),
            signature: signInternalLogs(KEY, SOURCE, TEAM_ID),
        },
        { name: 'no configured key', keys: '', signature: signInternalLogs(KEY, SOURCE, TEAM_ID) },
        { name: 'a source with no policy', signature: signInternalLogs(KEY, 'not_a_source', TEAM_ID) },
        { name: 'an inherited property as source', signature: signInternalLogs(KEY, 'constructor', TEAM_ID) },
        { name: 'the prototype as source', signature: signInternalLogs(KEY, '__proto__', TEAM_ID) },
    ])('bills a batch with $name', ({ signature, keys = KEY, teams = String(TEAM_ID) }) => {
        expect(new InternalLogsVerifier(keys, teams).verify(signature, TEAM_ID)).toBeUndefined()
    })

    it('refuses to sign a source that cannot go into the header', () => {
        expect(() => signInternalLogs(KEY, 'hog.flow', TEAM_ID)).toThrow('invalid source')
    })

    // Producers and consumers deploy separately, so a format change must be a new version prefix.
    it('keeps the v1 signature format stable', () => {
        expect(signInternalLogs(KEY, SOURCE, TEAM_ID)).toEqual(
            'v1.hog_flow.19fff1aa238f719386f3b7f841da431a5d2f8cf2908a42c1982858a78eb0e59a'
        )
    })
})
