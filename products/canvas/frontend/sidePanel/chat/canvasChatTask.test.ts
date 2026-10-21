import { canvasChatState, canvasChatTaskId } from './canvasChatTask'

describe('canvas chat task', () => {
    const versions = [
        { taskId: 'task-b', createdByUuid: 'user-b' },
        { taskId: 'task-a', createdByUuid: 'user-a' },
        { taskId: 'task-a-old', createdByUuid: 'user-a' },
    ]

    it.each([
        {
            name: "shows this person's newest run instead of another person's live run",
            startedTaskId: null,
            generationTaskId: 'task-b',
            generationTaskCreatorUuid: 'user-b',
            currentUserUuid: 'user-a',
            expected: 'task-a',
        },
        {
            name: 'shows the live run when this person started it',
            startedTaskId: null,
            generationTaskId: 'task-a-live',
            generationTaskCreatorUuid: 'user-a',
            currentUserUuid: 'user-a',
            expected: 'task-a-live',
        },
        {
            name: 'shows nothing to a person with no run on the canvas',
            startedTaskId: null,
            generationTaskId: 'task-b',
            generationTaskCreatorUuid: 'user-b',
            currentUserUuid: 'user-c',
            expected: null,
        },
        {
            name: 'prefers the run just started here while the record catches up',
            startedTaskId: 'task-new',
            generationTaskId: 'task-b',
            generationTaskCreatorUuid: 'user-b',
            currentUserUuid: 'user-a',
            expected: 'task-new',
        },
    ])('$name', ({ expected, ...args }) => {
        expect(canvasChatTaskId({ versions, ...args })).toBe(expected)
    })

    const task = (
        status: string | null
    ): { id: string; title: string; latest_run: { id: string; status: string } | null } => ({
        id: 'task-a',
        title: 'Signups board',
        latest_run: status ? { id: 'run-1', status } : null,
    })

    it.each([
        {
            name: 'a send in flight is starting',
            chatTask: task('completed'),
            starting: true,
            startError: null,
            expected: 'starting',
        },
        {
            name: 'a queued run is starting, not running',
            chatTask: task('queued'),
            starting: false,
            startError: null,
            expected: 'starting',
        },
        {
            name: 'an agent at work is running',
            chatTask: task('in_progress'),
            starting: false,
            startError: null,
            expected: 'running',
        },
        {
            name: 'an open run whose agent finished its turn is awaiting',
            chatTask: task('in_progress'),
            starting: false,
            startError: null,
            agentTurnActive: false,
            expected: 'awaiting',
        },
        {
            name: 'a completed run is finished',
            chatTask: task('completed'),
            starting: false,
            startError: null,
            expected: 'finished',
        },
        {
            name: 'a cancelled run is failed',
            chatTask: task('cancelled'),
            starting: false,
            startError: null,
            expected: 'failed',
        },
    ])('reads the chat as $expected when $name', ({ expected, ...args }) => {
        expect(canvasChatState({ chatTaskId: 'task-a', ...args })).toBe(expected)
    })

    it('says the run never started when the tasks API refused it', () => {
        expect(
            canvasChatState({ chatTaskId: null, chatTask: null, starting: false, startError: 'Runs are not available' })
        ).toBe('start-failed')
    })
})
