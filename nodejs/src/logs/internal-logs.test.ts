import { InternalLogsVerifier, signInternalLogs } from './internal-logs'

const KEY = 'internal-logs-test-key'
const OTHER_KEY = 'internal-logs-other-key'
const SOURCE = 'hog_flow'
const TEAM_ID = 2
const OTHER_TEAM_ID = 3
const SIGNED_AT = new Date('2026-10-27T12:00:00Z')
const CREATED_AT = '2026-10-27T12:01:00.123456789+00:00'

describe('InternalLogsVerifier', () => {
    it.each([
        {
            name: 'accepts a batch signed with the newest key',
            signature: signInternalLogs(KEY, SOURCE, TEAM_ID, SIGNED_AT),
        },
        {
            name: 'accepts a batch signed with an older key during rotation',
            keys: `${OTHER_KEY},${KEY}`,
            signature: signInternalLogs(KEY, SOURCE, TEAM_ID, SIGNED_AT),
        },
        {
            name: 'accepts a batch on a wildcard allowlist',
            teams: '*',
            signature: signInternalLogs(KEY, SOURCE, TEAM_ID, SIGNED_AT),
        },
        {
            name: 'accepts a producer clock that runs ahead of capture',
            createdAt: '2026-10-27T11:56:00Z',
            signature: signInternalLogs(KEY, SOURCE, TEAM_ID, SIGNED_AT),
        },
    ])('$name', ({ signature, keys = KEY, teams = String(TEAM_ID), createdAt = CREATED_AT }) => {
        expect(new InternalLogsVerifier(keys, teams).verify(signature, TEAM_ID, createdAt)).toEqual({
            source: SOURCE,
            billed: false,
            teamRules: false,
        })
    })

    it.each([
        { name: 'no header', signature: undefined },
        { name: 'a malformed signature', signature: 'v1.not-a-signature' },
        { name: 'an unknown key', signature: signInternalLogs(OTHER_KEY, SOURCE, TEAM_ID, SIGNED_AT) },
        { name: "another team's signature", signature: signInternalLogs(KEY, SOURCE, OTHER_TEAM_ID, SIGNED_AT) },
        {
            name: 'a signature moved to another source',
            signature: signInternalLogs(KEY, SOURCE, TEAM_ID, SIGNED_AT).replace(`.${SOURCE}.`, '.hog_function.'),
        },
        {
            name: 'a team not on the allowlist',
            teams: String(OTHER_TEAM_ID),
            signature: signInternalLogs(KEY, SOURCE, TEAM_ID, SIGNED_AT),
        },
        { name: 'no configured key', keys: '', signature: signInternalLogs(KEY, SOURCE, TEAM_ID, SIGNED_AT) },
        { name: 'a source with no policy', signature: signInternalLogs(KEY, 'not_a_source', TEAM_ID, SIGNED_AT) },
        {
            name: 'an inherited property as source',
            signature: signInternalLogs(KEY, 'constructor', TEAM_ID, SIGNED_AT),
        },
        { name: 'the prototype as source', signature: signInternalLogs(KEY, '__proto__', TEAM_ID, SIGNED_AT) },
        {
            name: 'a signature replayed after the window',
            createdAt: '2026-10-27T12:05:01Z',
            signature: signInternalLogs(KEY, SOURCE, TEAM_ID, SIGNED_AT),
        },
        { name: 'no created_at header', createdAt: null, signature: signInternalLogs(KEY, SOURCE, TEAM_ID, SIGNED_AT) },
        {
            name: 'an unparseable created_at header',
            createdAt: 'not-a-date',
            signature: signInternalLogs(KEY, SOURCE, TEAM_ID, SIGNED_AT),
        },
    ])(
        'bills a batch with $name',
        ({ signature, keys = KEY, teams = String(TEAM_ID), createdAt = CREATED_AT as string | null }) => {
            const verifier = new InternalLogsVerifier(keys, teams)
            expect(verifier.verify(signature, TEAM_ID, createdAt ?? undefined)).toBeUndefined()
        }
    )

    it('refuses to sign a source that cannot go into the header', () => {
        expect(() => signInternalLogs(KEY, 'hog.flow', TEAM_ID, SIGNED_AT)).toThrow('invalid source')
    })

    // Producers and consumers deploy separately, so a format change must be a new version prefix.
    it('keeps the v1 signature format stable', () => {
        expect(signInternalLogs(KEY, SOURCE, TEAM_ID, SIGNED_AT)).toEqual(
            'v1.hog_flow.1793102400.af443fe982b21dc42052d7d373d7b135c1d709955e8d5309a1bf84a2e8583c3d'
        )
    })
})
