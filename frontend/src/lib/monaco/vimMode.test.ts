import { setupVimMode } from 'lib/monaco/vimMode'

const mockAdapter: any = {
    addOverlay: () => {},
    removeOverlay: () => {},
    highlightRanges: () => {},
    getSearchCursor: () => ({}),
    statusBar: { closeInput: () => {}, setSec: () => {} },
    dispose: () => {},
}

jest.mock('monaco-vim', () => ({
    VimMode: { Vim: { getRegisterController: () => ({ pushText: () => {} }) } },
    initVimMode: () => mockAdapter,
}))

describe('setupVimMode', () => {
    const tooLarge = (): never => {
        throw new SyntaxError('Invalid regular expression: /aaa/: Regular expression too large')
    }
    const start = (): { dispose: () => void } =>
        setupVimMode({ getDomNode: () => null } as any, document.createElement('div'))

    beforeEach(() => {
        mockAdapter.getSearchCursor = () => ({})
    })

    it('searches nothing when the browser refuses to compile the pattern', () => {
        mockAdapter.getSearchCursor = tooLarge
        const handle = start()

        const cursor = mockAdapter.getSearchCursor(/aaa/, { line: 0, ch: 0 })

        expect(cursor.getMatches()).toEqual([])
        expect(cursor.find(false)).toBe(false)
        expect(cursor.from()).toBeNull()
        handle.dispose()
    })

    it('leaves a usable search cursor alone', () => {
        const cursor = { find: () => 'match' }
        mockAdapter.getSearchCursor = () => cursor
        const handle = start()

        expect(mockAdapter.getSearchCursor(/aaa/, { line: 0, ch: 0 })).toBe(cursor)
        handle.dispose()
    })

    it('still throws anything that is not a rejected pattern', () => {
        mockAdapter.getSearchCursor = () => {
            throw new TypeError('model is disposed')
        }
        const handle = start()

        expect(() => mockAdapter.getSearchCursor(/aaa/, { line: 0, ch: 0 })).toThrow(TypeError)
        handle.dispose()
    })

    it('stops guarding the search cursor once disposed', () => {
        mockAdapter.getSearchCursor = tooLarge

        start().dispose()

        expect(() => mockAdapter.getSearchCursor(/aaa/, { line: 0, ch: 0 })).toThrow(SyntaxError)
    })
})
