// Run with: node --test .github/scripts/ci-rerun-transient-failures.test.js
//
// The workflow only runs post-merge (workflow_run triggers fire from the default
// branch), so this unit test is the sole pre-merge signal that the classifier
// reruns runner-shutdown flakes while never masking a genuine failure.

const test = require('node:test')
const assert = require('node:assert/strict')

const { shouldRerun, isTransientFailure } = require('./ci-rerun-transient-failures')

const CANCELED = 'The operation was canceled.'
const SHUTDOWN = 'The runner has received a shutdown signal. This can happen when the runner service is stopped.'
const GATE_EXIT = 'Process completed with exit code 1.'
const TYPE_ERROR = "Expected 2 arguments, but got 1."

const typecheckShutdown = { name: 'Frontend typechecking', conclusion: 'failure', failureMessages: [CANCELED] }
const gateFail = { name: 'Frontend Tests Pass', conclusion: 'failure', failureMessages: [GATE_EXIT] }
const jestGenuine = { name: 'Jest test (EE - 1)', conclusion: 'failure', failureMessages: [TYPE_ERROR] }

const SHOULD_RERUN_CASES = [
    {
        description: 'transient typecheck + consequential gate -> rerun',
        input: { conclusion: 'failure', runAttempt: 1, jobs: [typecheckShutdown, gateFail] },
        expected: true,
    },
    {
        description: 'shutdown-signal wording is also transient',
        input: {
            conclusion: 'failure',
            runAttempt: 1,
            jobs: [{ name: 'Frontend typechecking', conclusion: 'failure', failureMessages: [SHUTDOWN] }, gateFail],
        },
        expected: true,
    },
    {
        description: 'genuine leaf failure -> no rerun',
        input: { conclusion: 'failure', runAttempt: 1, jobs: [jestGenuine, gateFail] },
        expected: false,
    },
    {
        description: 'mixed transient + genuine -> no rerun (never mask a real failure)',
        input: { conclusion: 'failure', runAttempt: 1, jobs: [typecheckShutdown, jestGenuine, gateFail] },
        expected: false,
    },
    {
        description: 'only the gate failed, no leaf cause -> no rerun',
        input: { conclusion: 'failure', runAttempt: 1, jobs: [gateFail] },
        expected: false,
    },
    {
        description: 'attempt cap reached -> no rerun',
        input: { conclusion: 'failure', runAttempt: 3, jobs: [typecheckShutdown, gateFail] },
        expected: false,
    },
    {
        description: 'run did not fail -> no rerun',
        input: { conclusion: 'success', runAttempt: 1, jobs: [typecheckShutdown] },
        expected: false,
    },
    {
        description: 'transient job with no failure annotations -> no rerun (empty is not transient)',
        input: {
            conclusion: 'failure',
            runAttempt: 1,
            jobs: [{ name: 'Frontend typechecking', conclusion: 'failure', failureMessages: [] }, gateFail],
        },
        expected: false,
    },
]

test('shouldRerun', async (t) => {
    for (const { description, input, expected } of SHOULD_RERUN_CASES) {
        await t.test(description, () => {
            assert.equal(shouldRerun(input), expected)
        })
    }
})

const IS_TRANSIENT_CASES = [
    { description: 'canceled message', messages: [CANCELED], expected: true },
    { description: 'shutdown-signal message', messages: [SHUTDOWN], expected: true },
    { description: 'empty annotations are not transient', messages: [], expected: false },
    { description: 'a real error alongside a cancel is not transient', messages: [CANCELED, TYPE_ERROR], expected: false },
    { description: 'generic exit code is not transient', messages: [GATE_EXIT], expected: false },
]

test('isTransientFailure', async (t) => {
    for (const { description, messages, expected } of IS_TRANSIENT_CASES) {
        await t.test(description, () => {
            assert.equal(isTransientFailure(messages), expected)
        })
    }
})
