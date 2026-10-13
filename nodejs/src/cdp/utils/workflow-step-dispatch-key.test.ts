import { buildWorkflowStepDispatchKey, parseWorkflowStepDispatchKey } from './workflow-step-dispatch-key'

describe('workflow step dispatch keys', () => {
    const jobId = 'b1f0c2d4-0000-4000-8000-000000000001'

    it.each([0, 1, 2])('round trips an action with colons for rerun %s', (rerunAttempts) => {
        const key = buildWorkflowStepDispatchKey(jobId, 'task:node', 3, rerunAttempts)
        expect(parseWorkflowStepDispatchKey(key)).toEqual({ jobId, actionId: 'task:node' })
        expect(key).toBe(`${jobId}:task:node:3${rerunAttempts ? `.r${rerunAttempts}` : ''}`)
        expect(buildWorkflowStepDispatchKey(jobId, 'task:node', 3, rerunAttempts)).toBe(key)
        expect(buildWorkflowStepDispatchKey(jobId, 'task:node', 4, rerunAttempts)).not.toBe(key)
        expect(buildWorkflowStepDispatchKey(jobId, 'task:node', 3, rerunAttempts + 1)).not.toBe(key)
    })

    it.each([
        'nope',
        'bad:task:3',
        `${jobId}::3`,
        `${jobId}:task:`,
        `${jobId}:task:-1`,
        `${jobId}:task:1.5`,
        `${jobId}:task:NaN`,
        `${jobId}:task:3.r0`,
        `${jobId}:task:3.r-1`,
        `${jobId}:task:9007199254740992`,
        `${jobId}:task:3.r9007199254740992`,
    ])('rejects an invalid key: %s', (key) => {
        expect(parseWorkflowStepDispatchKey(key)).toBeNull()
    })
})
