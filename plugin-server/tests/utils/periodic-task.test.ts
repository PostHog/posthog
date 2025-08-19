import { PeriodicTask } from '../../src/utils/periodic-task'

describe('PeriodicTask', () => {
    describe('updates completion status', () => {
        it('on success', async () => {
            const fn = jest.fn()
            const task = new PeriodicTask('test', fn, 1000)
            expect(fn).toHaveBeenCalled()
            expect(task.isRunning()).toEqual(true)
            await task.stop()
            expect(task.isRunning()).toEqual(false)
        })

        it('on failure', async () => {
            const fn = jest.fn(() => {
                throw new Error()
            })
            const task = new PeriodicTask('test', fn, 1000)
            expect(fn).toHaveBeenCalled()
            await task.stop()
            expect(task.isRunning()).toEqual(false)
        })
    })
})
