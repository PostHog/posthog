import { scene } from './Max'

describe('Max scene parameters', () => {
    const validTaskId = '0199ed4a-5c03-0000-3220-df21df612e95'

    it('accepts a UUID task ID', () => {
        expect(scene.paramsToProps?.({ params: {}, searchParams: { task: validTaskId }, hashParams: {} })).toEqual({
            taskId: validTaskId,
        })
    })

    it.each(['.', '..', '../../99', 'task-1'])('rejects invalid task ID %s', (taskId) => {
        expect(scene.paramsToProps?.({ params: {}, searchParams: { task: taskId }, hashParams: {} })).toEqual({
            taskId: undefined,
        })
    })
})
