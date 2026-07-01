import { mergeProgressStep, parseTaskRunStreamMessage, TaskRunProgressStep } from './taskRunStreamLogic'

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
})
