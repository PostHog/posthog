import { collab, getVersion } from '@tiptap/pm/collab'
import { schema } from '@tiptap/pm/schema-basic'
import { EditorState } from '@tiptap/pm/state'

import { TTEditor } from 'lib/components/RichContentEditor/types'

import { applyRemoteStep, RemoteStep } from './notebookCollabLogic'
import { REMOTE_PRESENCE_META } from './RemotePresenceExtension'

jest.mock('posthog-js', () => ({ captureException: jest.fn() }))
jest.mock('@posthog/lemon-ui', () => ({
    ...jest.requireActual('@posthog/lemon-ui'),
    lemonToast: { error: jest.fn() },
}))

const LOCAL_CLIENT_ID = 'local-client'
const REMOTE_CLIENT_ID = 'remote-client'

function createMockEditor(initialVersion: number = 0): TTEditor {
    const doc = schema.node('doc', null, [schema.node('paragraph', null, [schema.text('abc')])])
    let state = EditorState.create({
        doc,
        schema,
        plugins: [collab({ version: initialVersion, clientID: LOCAL_CLIENT_ID })],
    })
    const dispatch = jest.fn((tr: any) => {
        state = state.apply(tr)
    })
    return {
        get state() {
            return state
        },
        view: { dispatch },
    } as unknown as TTEditor
}

function insertStepJSON(at: number, text: string): Record<string, any> {
    return {
        stepType: 'replace',
        from: at,
        to: at,
        slice: { content: [{ type: 'text', text }] },
    }
}

function presence(head: number): RemoteStep['presence'] {
    return { userId: 42, userName: 'Remote User', head }
}

describe('notebookCollabLogic', () => {
    describe('applyRemoteStep', () => {
        it('applies a step when remote.version matches local + 1', () => {
            const editor = createMockEditor(0)
            const startDoc = editor.state.doc.textContent

            applyRemoteStep(editor, {
                step: insertStepJSON(4, 'X'),
                clientId: REMOTE_CLIENT_ID,
                version: 1,
            })

            expect(editor.view.dispatch).toHaveBeenCalledTimes(1)
            expect(getVersion(editor.state)).toBe(1)
            expect(editor.state.doc.textContent).toBe(`${startDoc}X`)
        })

        it('skips the step when remote.version is behind, but still dispatches presence', () => {
            const editor = createMockEditor(5)
            const startDoc = editor.state.doc.textContent

            applyRemoteStep(editor, {
                step: insertStepJSON(4, 'X'),
                clientId: REMOTE_CLIENT_ID,
                version: 3,
                presence: presence(2),
            })

            expect(editor.view.dispatch).toHaveBeenCalledTimes(1)
            const [tr] = (editor.view.dispatch as jest.Mock).mock.calls[0]
            expect(tr.getMeta(REMOTE_PRESENCE_META)).toEqual({
                clientId: REMOTE_CLIENT_ID,
                userId: 42,
                userName: 'Remote User',
                head: 2,
                lastSeenAt: expect.any(Number),
            })
            // doc and collab version should be untouched
            expect(editor.state.doc.textContent).toBe(startDoc)
            expect(getVersion(editor.state)).toBe(5)
        })

        it('does nothing when remote.version is behind and no presence is attached', () => {
            const editor = createMockEditor(5)

            applyRemoteStep(editor, {
                step: insertStepJSON(4, 'X'),
                clientId: REMOTE_CLIENT_ID,
                version: 3,
            })

            expect(editor.view.dispatch).not.toHaveBeenCalled()
        })

        it('skips entirely when remote.version is ahead (out of order)', () => {
            const editor = createMockEditor(0)

            applyRemoteStep(editor, {
                step: insertStepJSON(4, 'X'),
                clientId: REMOTE_CLIENT_ID,
                version: 5,
                presence: presence(2),
            })

            expect(editor.view.dispatch).not.toHaveBeenCalled()
            expect(getVersion(editor.state)).toBe(0)
        })

        it('attaches presence meta to the applied step transaction', () => {
            const editor = createMockEditor(0)

            applyRemoteStep(editor, {
                step: insertStepJSON(4, 'X'),
                clientId: REMOTE_CLIENT_ID,
                version: 1,
                presence: presence(5),
            })

            const [tr] = (editor.view.dispatch as jest.Mock).mock.calls[0]
            expect(tr.getMeta(REMOTE_PRESENCE_META)).toEqual({
                clientId: REMOTE_CLIENT_ID,
                userId: 42,
                userName: 'Remote User',
                head: 5,
                lastSeenAt: expect.any(Number),
            })
            expect(tr.docChanged).toBe(true)
        })

        it('swallows errors from malformed steps instead of throwing', () => {
            const editor = createMockEditor(0)

            expect(() =>
                applyRemoteStep(editor, {
                    step: { stepType: 'totally-bogus' } as any,
                    clientId: REMOTE_CLIENT_ID,
                    version: 1,
                })
            ).not.toThrow()
            expect(editor.view.dispatch).not.toHaveBeenCalled()
        })
    })
})
