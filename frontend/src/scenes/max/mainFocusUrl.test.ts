import { MainFocusUrlInput, mainFocusUrl } from './mainFocusUrl'

describe('mainFocusUrl', () => {
    // The first row is the reported bug: the new view's panel has a run open, but its `conversationId`
    // is always null, so deriving the link from the conversation alone sends the user to a blank `/ai`.
    const cases: [string, MainFocusUrlInput, string][] = [
        [
            'new view with a run open',
            { isNewView: true, activeTaskId: 'task-1', conversationId: null },
            '/tasks/task-1',
        ],
        ['new view with nothing open', { isNewView: true, conversationId: null }, '/ai'],
        [
            'legacy view with a chat open',
            { isNewView: false, conversationId: 'conversation-1' },
            '/ai?chat=conversation-1',
        ],
        ['legacy view with nothing open', { isNewView: false, conversationId: null }, '/ai'],
    ]

    it.each(cases)('opens what the panel is showing: %s', (_name, input, expected) => {
        expect(mainFocusUrl(input)).toBe(expected)
    })
})
