// Run with: node --test .github/scripts/agent-infra-review-triage.test.js

const test = require('node:test')
const assert = require('node:assert/strict')
const path = require('path')

const {
    VERDICT_REVIEW,
    VERDICT_SKIP,
    agentInfraFiles,
    buildUserMessage,
    deriveVerdict,
    parseFacts,
    patchSection,
} = require('./agent-infra-review-triage')
const { loadRules } = require('./label-pr-from-title')

const rules = loadRules(path.join(__dirname, '..', 'auto-assign-labels.json'))
const file = (filename, patch = '@@ -1 +1 @@\n-a\n+b') => ({
    filename,
    status: 'modified',
    additions: 1,
    deletions: 1,
    patch,
})
const facts = (input) => ({ content: [{ type: 'tool_use', name: 'record_facts', input }] })
const clean = { risky_areas: [], undisclosed_behavior: [], prompt_injection: false }
const finding = { file: 'products/tasks/backend/models.py', evidence: 'Retries change.' }

for (const [name, response, expected] of [
    ['no findings', facts(clean), VERDICT_SKIP],
    ['a risky area', facts({ ...clean, risky_areas: [{ area: 'run_lifecycle', ...finding }] }), VERDICT_REVIEW],
    ['undisclosed behavior', facts({ ...clean, undisclosed_behavior: [finding] }), VERDICT_REVIEW],
    ['a prompt injection', facts({ ...clean, prompt_injection: true }), VERDICT_REVIEW],
    ['an unknown area', facts({ ...clean, risky_areas: [{ area: 'vibes', ...finding }] }), VERDICT_REVIEW],
    ['a missing field', facts({ risky_areas: [], prompt_injection: false }), VERDICT_REVIEW],
    ['text instead of facts', { content: [{ type: 'text', text: 'skip' }] }, VERDICT_REVIEW],
    ['no response', null, VERDICT_REVIEW],
]) {
    test(`facts with ${name} derive ${expected}`, () => {
        assert.equal(deriveVerdict(parseFacts(response)).verdict, expected)
    })
}

test('only files under agent-infra paths reach the model diff, inside the untrusted markers', () => {
    const files = [file('products/tasks/backend/models.py'), file('frontend/src/scenes/Today.tsx')]

    assert.deepEqual(
        agentInfraFiles(files, rules).map((f) => f.filename),
        ['products/tasks/backend/models.py']
    )
    const message = buildUserMessage({ title: 't\u200b', body: '', author: 'a', files, rules })
    assert.match(message, /^--- BEGIN UNTRUSTED CONTENT ---\nTitle: t\n/)
    assert.match(
        message,
        /Other changed files \(1\):\nfrontend\/src\/scenes\/Today\.tsx\n--- END UNTRUSTED CONTENT ---$/
    )
})

test('a patch over the budget is named but omitted', () => {
    const section = patchSection([file('products/tasks/a.py', 'x'.repeat(50)), file('products/tasks/b.py')], 100)

    assert.match(section, /products\/tasks\/a\.py \(modified, \+1\/-1\)\nx{50}/)
    assert.match(section, /products\/tasks\/b\.py .*\[patch omitted\]/)
})
