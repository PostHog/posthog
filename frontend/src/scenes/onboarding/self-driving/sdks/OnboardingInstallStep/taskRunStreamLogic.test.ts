import {
    cloudRunCompletionReport,
    mergeProgressStep,
    parseTaskRunStreamMessage,
    TaskRunProgressStep,
    taskRunPrUrl,
    TaskRunStreamState,
} from './taskRunStreamLogic'

function step(overrides: Partial<TaskRunProgressStep> = {}): TaskRunProgressStep {
    return {
        step: 'clone',
        status: 'in_progress',
        label: 'Cloning repository',
        group: 'setup',
        detail: null,
        ...overrides,
    }
}

function runState(overrides: Partial<TaskRunStreamState> = {}): TaskRunStreamState {
    return {
        status: 'in_progress',
        stage: 'wizard',
        output: null,
        branch: null,
        error_message: null,
        updated_at: '2026-01-01T00:05:00Z',
        completed_at: null,
        ...overrides,
    }
}

describe('taskRunStreamLogic helpers', () => {
    describe('mergeProgressStep', () => {
        it('appends a new step', () => {
            expect(mergeProgressStep([], step())).toEqual([step()])
        })

        it('updates an existing (group, step) in place, preserving order', () => {
            const clone = step({ step: 'clone' })
            const wizard = step({ step: 'wizard', label: 'Running wizard' })
            const cloneDone = step({ step: 'clone', status: 'completed', label: 'Cloned' })
            expect(mergeProgressStep([clone, wizard], cloneDone)).toEqual([cloneDone, wizard])
        })

        it('treats the same step name in a different group as distinct', () => {
            const inSetup = step({ step: 'open', group: 'setup' })
            const inPr = step({ step: 'open', group: 'pr_create' })
            expect(mergeProgressStep([inSetup], inPr)).toEqual([inSetup, inPr])
        })
    })

    describe('parseTaskRunStreamMessage', () => {
        it('parses a task_run_state event with all fields', () => {
            const raw = JSON.stringify({
                type: 'task_run_state',
                status: 'failed',
                stage: 'wizard',
                output: { pr_url: 'https://x/pull/1' },
                branch: 'main',
                error_message: 'boom',
                updated_at: '2026-01-01T00:00:00Z',
                completed_at: '2026-01-01T00:01:00Z',
            })
            expect(parseTaskRunStreamMessage(raw)).toEqual({
                kind: 'state',
                state: {
                    status: 'failed',
                    stage: 'wizard',
                    output: { pr_url: 'https://x/pull/1' },
                    branch: 'main',
                    error_message: 'boom',
                    updated_at: '2026-01-01T00:00:00Z',
                    completed_at: '2026-01-01T00:01:00Z',
                },
            })
        })

        it('defaults missing optional task_run_state fields to null', () => {
            const raw = JSON.stringify({
                type: 'task_run_state',
                status: 'in_progress',
                updated_at: '2026-01-01T00:00:00Z',
            })
            expect(parseTaskRunStreamMessage(raw)).toEqual({
                kind: 'state',
                state: {
                    status: 'in_progress',
                    stage: null,
                    output: null,
                    branch: null,
                    error_message: null,
                    updated_at: '2026-01-01T00:00:00Z',
                    completed_at: null,
                },
            })
        })

        it('parses a _posthog/progress notification into a step', () => {
            const raw = JSON.stringify({
                type: 'notification',
                notification: {
                    method: '_posthog/progress',
                    params: {
                        step: 'clone',
                        status: 'in_progress',
                        label: 'Cloning',
                        group: 'setup',
                        detail: 'shallow',
                    },
                },
            })
            expect(parseTaskRunStreamMessage(raw)).toEqual({
                kind: 'step',
                step: { step: 'clone', status: 'in_progress', label: 'Cloning', group: 'setup', detail: 'shallow' },
            })
        })

        it('defaults a step with no detail to null', () => {
            const raw = JSON.stringify({
                type: 'notification',
                notification: {
                    method: '_posthog/progress',
                    params: { step: 'clone', status: 'completed', label: 'Cloned', group: 'setup' },
                },
            })
            expect(parseTaskRunStreamMessage(raw)).toEqual({
                kind: 'step',
                step: { step: 'clone', status: 'completed', label: 'Cloned', group: 'setup', detail: null },
            })
        })

        it.each([
            [
                'a non-progress notification',
                { type: 'notification', notification: { method: 'other', params: { step: 'x' } } },
            ],
            [
                'a progress notification without params',
                { type: 'notification', notification: { method: '_posthog/progress' } },
            ],
            ['a notification without a notification field', { type: 'notification' }],
            ['a keepalive', { type: 'keepalive' }],
            ['an unknown type', { type: 'whatever' }],
        ])('returns null for %s', (_name, payload) => {
            expect(parseTaskRunStreamMessage(JSON.stringify(payload))).toBeNull()
        })

        it('throws on invalid JSON', () => {
            expect(() => parseTaskRunStreamMessage('not json')).toThrow(SyntaxError)
        })
    })

    describe('taskRunPrUrl', () => {
        it('prefers the terminal output url over the pr progress step', () => {
            const state = runState({ output: { pr_url: 'https://x/pull/2' } })
            const steps = [step({ step: 'pr', group: 'pr_create', detail: 'https://x/pull/1' })]
            expect(taskRunPrUrl(state, steps)).toBe('https://x/pull/2')
        })

        it('falls back to the pr progress step detail when the output has no url', () => {
            const steps = [step({ step: 'pr', group: 'pr_create', detail: 'https://x/pull/1' })]
            expect(taskRunPrUrl(runState(), steps)).toBe('https://x/pull/1')
        })

        it('ignores a pr step whose detail is not a url', () => {
            const steps = [step({ step: 'pr', group: 'pr_create', detail: 'Opening a pull request' })]
            expect(taskRunPrUrl(runState(), steps)).toBeNull()
        })

        it('returns null with no state and no pr step', () => {
            expect(taskRunPrUrl(null, [step()])).toBeNull()
        })
    })

    describe('cloudRunCompletionReport', () => {
        const startedAt = '2026-01-01T00:00:00Z'

        it('reports an observed transition into completed, with duration and the PR', () => {
            const report = cloudRunCompletionReport(
                runState({ status: 'in_progress' }),
                runState({
                    status: 'completed',
                    output: { pr_url: 'https://x/pull/1' },
                    completed_at: '2026-01-01T00:04:30Z',
                }),
                [],
                startedAt
            )
            expect(report).toEqual({
                status: 'completed',
                durationSeconds: 270,
                prOpened: true,
                prUrl: 'https://x/pull/1',
            })
        })

        it('reports a failed run with no PR opened', () => {
            const report = cloudRunCompletionReport(
                runState({ status: 'in_progress' }),
                runState({ status: 'failed', error_message: 'boom', completed_at: '2026-01-01T00:04:30Z' }),
                [],
                startedAt
            )
            expect(report).toEqual({ status: 'failed', durationSeconds: 270, prOpened: false, prUrl: null })
        })

        it('takes the PR url from the pr progress step when the output lacks one', () => {
            const report = cloudRunCompletionReport(
                runState({ status: 'in_progress' }),
                runState({ status: 'completed', completed_at: '2026-01-01T00:04:30Z' }),
                [step({ step: 'pr', group: 'pr_create', detail: 'https://x/pull/1' })],
                startedAt
            )
            expect(report).toMatchObject({ prOpened: true, prUrl: 'https://x/pull/1' })
        })

        it('falls back to updated_at for the duration when completed_at is missing', () => {
            const report = cloudRunCompletionReport(
                runState({ status: 'in_progress' }),
                runState({ status: 'cancelled', updated_at: '2026-01-01T00:02:00Z' }),
                [],
                startedAt
            )
            expect(report).toMatchObject({ status: 'cancelled', durationSeconds: 120 })
        })

        it('reports a null duration without a kickoff timestamp', () => {
            const report = cloudRunCompletionReport(
                runState({ status: 'in_progress' }),
                runState({ status: 'completed', completed_at: '2026-01-01T00:04:30Z' }),
                [],
                undefined
            )
            expect(report).toMatchObject({ durationSeconds: null })
        })

        it.each([
            ['the update is not terminal', runState({ status: 'in_progress' }), runState({ status: 'queued' })],
            // A stream (re)connecting to a finished run replays the terminal state with no prior
            // observation — the backend task_run_* events cover unwatched completions.
            ['no previous state was observed', null, runState({ status: 'completed' })],
            [
                'the previous state was already terminal',
                runState({ status: 'completed' }),
                runState({ status: 'completed' }),
            ],
        ])('returns null when %s', (_name, previous, state) => {
            expect(cloudRunCompletionReport(previous, state, [], startedAt)).toBeNull()
        })
    })
})
