import { MainFocusUrlInput, mainFocusUrl } from './mainFocusUrl'

describe('mainFocusUrl', () => {
    const cases: [string, MainFocusUrlInput, string | null][] = [
        [
            'new view with a run open',
            {
                isNewView: true,
                activeCreation: { streamKey: 'run-1', taskId: 'task-1', runId: 'run-1' },
                conversationId: null,
            },
            '/tasks/task-1?runId=run-1',
        ],
        [
            'new view with a run that never started',
            { isNewView: true, activeCreation: { streamKey: 'run-1', taskId: 'task-1' }, conversationId: null },
            '/tasks/task-1',
        ],
        [
            'new view with a task still being created',
            { isNewView: true, activeCreation: { streamKey: 'draft-1' }, conversationId: null },
            null,
        ],
        ['new view with nothing open', { isNewView: true, activeCreation: null, conversationId: null }, '/ai'],
        [
            'legacy view with a chat open',
            { isNewView: false, activeCreation: null, conversationId: 'conversation-1' },
            '/ai?chat=conversation-1',
        ],
        ['legacy view with nothing open', { isNewView: false, activeCreation: null, conversationId: null }, '/ai'],
    ]

    it.each(cases)('opens what the panel is showing: %s', (_name, input, expected) => {
        expect(mainFocusUrl(input)).toBe(expected)
    })
})
