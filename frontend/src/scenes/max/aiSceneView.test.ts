import { AiSceneViewInput, aiSceneView } from './aiSceneView'

describe('aiSceneView', () => {
    const cases: [string, AiSceneViewInput, 'runner' | 'chat'][] = [
        ['a bare /ai with the new view saved', { effectivePhaiView: 'new' }, 'runner'],
        ['a bare /ai with the legacy view saved', { effectivePhaiView: 'legacy' }, 'chat'],
        ['a task link with the legacy view saved', { taskId: 'task-1', effectivePhaiView: 'legacy' }, 'runner'],
        ['a chat link with the new view saved', { chatId: 'chat-1', effectivePhaiView: 'new' }, 'chat'],
        ['a chat link with the legacy view saved', { chatId: 'chat-1', effectivePhaiView: 'legacy' }, 'chat'],
        // Legacy Max writes `?chat=` itself once a conversation starts; a task added to that URL wins.
        ['a task and a chat in one URL', { taskId: 'task-1', chatId: 'chat-1', effectivePhaiView: 'new' }, 'runner'],
    ]

    it.each(cases)('%s', (_name, input, expected) => {
        expect(aiSceneView(input)).toBe(expected)
    })
})
