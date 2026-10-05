import { setupVimMode } from 'lib/monaco/vimMode'

jest.mock('monaco-vim', () => {
    const registerController = { pushText: jest.fn(), getRegister: jest.fn() }
    return {
        VimMode: { Vim: { getRegisterController: () => registerController } },
        initVimMode: (editor: any) => {
            const adapter = {
                statusBar: { closeInput: jest.fn(), setSec: jest.fn() },
                addOverlay: jest.fn(),
                enterVimMode: () => editor.updateOptions({ cursorBlinking: 'solid', cursorStyle: 'block' }),
                leaveVimMode: () => editor.updateOptions({ cursorBlinking: 'blink', cursorStyle: 'line' }),
                dispose: jest.fn(),
            }
            adapter.enterVimMode()
            return adapter
        },
    }
})

describe('setupVimMode', () => {
    it('keeps the normal mode block cursor blinking', () => {
        const options: Record<string, unknown> = {}
        const editor = {
            updateOptions: (update: Record<string, unknown>) => Object.assign(options, update),
            getDomNode: () => null,
        } as any

        const { vimMode, dispose } = setupVimMode(editor, document.createElement('div'))
        expect(options).toMatchObject({ cursorBlinking: 'blink', cursorStyle: 'block' })

        const adapter = vimMode as any
        adapter.leaveVimMode()
        adapter.enterVimMode()
        expect(options).toMatchObject({ cursorBlinking: 'blink', cursorStyle: 'block' })

        dispose()
        adapter.enterVimMode()
        expect(options).toMatchObject({ cursorBlinking: 'solid', cursorStyle: 'block' })
    })
})
