const test = require('node:test')
const assert = require('node:assert/strict')

const {
    VERDICT_REVIEW,
    VERDICT_SKIP,
    buildUserMessage,
    deriveVerdict,
    ownedDiff,
    diffHash,
    previousTriage,
    parseFacts,
    patchSection,
    triage,
    triagedRule,
} = require('./agent-infra-review-triage')

const rule = {
    paths: ['products/tasks/'],
    labels: ['feature/agent-infra'],
    review: { team: 'team-agent-infrastructure', label: 'agent-infra/review-needed' },
}
const file = (filename, patch = '@@ -1 +1 @@\n-a\n+b') => ({
    filename,
    status: 'modified',
    additions: 1,
    deletions: 1,
    patch,
})
const sameRepo = { full_name: 'PostHog/posthog' }
const pullRequest = (overrides = {}) => ({
    title: 't',
    body: '',
    user: { login: 'a' },
    head: { repo: sameRepo },
    base: { repo: sameRepo },
    ...overrides,
})
const facts = (input) => ({ content: [{ type: 'tool_use', name: 'record_facts', input }] })
const clean = { risky_areas: [], undisclosed_behavior: [], prompt_injection: false }
const finding = { file: 'products/tasks/backend/models.py', evidence: 'Retries change.' }

for (const [name, response, expected] of [
    ['no findings', facts(clean), VERDICT_SKIP],
    [
        'a risky area',
        facts({ ...clean, risky_areas: [{ area: 'run_lifecycle', ...finding }] }),
        VERDICT_REVIEW,
    ],
    ['undisclosed behavior', facts({ ...clean, undisclosed_behavior: [finding] }), VERDICT_REVIEW],
    ['a prompt injection', facts({ ...clean, prompt_injection: true }), VERDICT_REVIEW],
    [
        'an unknown area',
        facts({ ...clean, risky_areas: [{ area: 'vibes', ...finding }] }),
        VERDICT_REVIEW,
    ],
    ['a missing field', facts({ risky_areas: [], prompt_injection: false }), VERDICT_REVIEW],
    ['text instead of facts', { content: [{ type: 'text', text: 'skip' }] }, VERDICT_REVIEW],
    ['no response', null, VERDICT_REVIEW],
]) {
    test(`facts with ${name} derive ${expected}`, () => {
        assert.equal(deriveVerdict(parseFacts(response)).verdict, expected)
    })
}

for (const [name, pullRequestOverrides, files] of [
    ['a fork', { head: { repo: { full_name: 'someone/posthog' } } }, [file('products/tasks/a.py')]],
    ['a deleted fork', { head: { repo: null } }, [file('products/tasks/a.py')]],
    ['a file with no patch', {}, [file('products/tasks/a.py', undefined)]],
    ['a patch over the budget', {}, [file('products/tasks/a.py', 'x'.repeat(70_000))]],
]) {
    test(`${name} goes to review without the model`, async () => {
        const diff = ownedDiff(files, rule)
        const result = await triage({ pullRequest: pullRequest(pullRequestOverrides), files, diff })

        assert.equal(result.verdict, VERDICT_REVIEW)
    })
}

test('a patch that overflows the budget is truncated to what is left and marked', () => {
    const section = patchSection(
        [file('products/tasks/a.py', 'x'.repeat(50)), file('products/tasks/b.py', 'y'.repeat(50))],
        80
    )

    assert.match(section.text, /a\.py \(modified, \+1\/-1\)\nx{50}\n/)
    assert.match(section.text, /b\.py \(modified, \+1\/-1\)\ny{30}\n\[truncated 20 characters\]/)
    assert.deepEqual(section.incomplete, ['products/tasks/b.py'])
})

test('generated files are named but kept out of the diff', () => {
    const files = [
        file('products/tasks/backend/__snapshots__/test_api.ambr', 'SNAPSHOT'),
        file('products/tasks/backend/models.py', 'MODEL'),
        file('frontend/src/scenes/Today.tsx', 'TODAY'),
    ]
    const diff = ownedDiff(files, rule)
    const message = buildUserMessage({ pullRequest: pullRequest(), files, diff })

    assert.doesNotMatch(message, /SNAPSHOT|TODAY/)
    assert.match(message, /MODEL/)
    assert.match(message, /not shown \(1\):\n.*__snapshots__\/test_api\.ambr\n/)
})

test('untrusted content is wrapped in markers with invisible characters removed', () => {
    const title = `t${String.fromCharCode(0x200b)}`
    const files = [file('frontend/src/scenes/Today.tsx')]
    const diff = ownedDiff(files, rule)
    const message = buildUserMessage({ pullRequest: pullRequest({ title }), files, diff })

    assert.match(message, /^--- BEGIN UNTRUSTED CONTENT ---\nTitle: t\n/)
    assert.match(message, /Today\.tsx\n--- END UNTRUSTED CONTENT ---$/)
})

for (const [name, rules] of [
    ['no rule', [{ labels: ['x'] }]],
    ['two rules', [rule, { ...rule, labels: ['y'] }]],
]) {
    test(`a config with ${name} carrying review is rejected`, () => {
        assert.throws(() => triagedRule(rules), /Expected one label rule/)
    })
}

test('the diff hash changes with an owned patch and ignores other files', () => {
    const owned = [file('products/tasks/a.py', 'one')]
    const hash = diffHash(ownedDiff([...owned, file('frontend/a.tsx', 'x')], rule))

    assert.equal(hash, diffHash(ownedDiff([...owned, file('frontend/a.tsx', 'y')], rule)))
    assert.notEqual(hash, diffHash(ownedDiff([file('products/tasks/a.py', 'two')], rule)))
})

for (const [name, statuses, expected] of [
    [
        'a matching hash',
        [{ context: 'agent-infra-review-triage', description: 'skip abc' }],
        'skip abc',
    ],
    ['another hash', [{ context: 'agent-infra-review-triage', description: 'skip def' }], null],
    ['another context', [{ context: 'ci', description: 'skip abc' }], null],
    ['a failed lookup', null, null],
]) {
    const reused = expected === null ? 'not reused' : 'reused'
    test(`a previous triage with ${name} is ${reused}`, async (t) => {
        t.mock.method(globalThis, 'fetch', async () => ({
            ok: statuses !== null,
            status: statuses === null ? 404 : 200,
            json: async () => statuses,
            text: async () => 'not found',
        }))

        assert.equal(await previousTriage(['sha'], 'abc'), expected)
    })
}
