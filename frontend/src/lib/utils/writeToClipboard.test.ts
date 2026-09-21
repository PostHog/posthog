import { writeToClipboard } from './writeToClipboard'

describe('writeToClipboard', () => {
    const originalClipboard = navigator.clipboard
    const execCommand = jest.fn(() => true)

    beforeEach(() => {
        jest.clearAllMocks()
        document.execCommand = execCommand as unknown as typeof document.execCommand
    })

    afterEach(() => {
        Object.defineProperty(navigator, 'clipboard', { value: originalClipboard, configurable: true })
    })

    function setClipboard(clipboard: unknown): void {
        Object.defineProperty(navigator, 'clipboard', { value: clipboard, configurable: true })
    }

    // The toolbar runs inside customer pages served over plain HTTP, where navigator.clipboard does not
    // exist at all, and inside embedded contexts where writeText rejects. Both fall through to the
    // selection route, so dropping it would leave every copy control in the toolbar doing nothing.
    it.each([
        ['the Clipboard API writes', { writeText: jest.fn(() => Promise.resolve()) }, true, 'copied', 0],
        ['the Clipboard API is absent', undefined, true, 'copied', 1],
        [
            'the Clipboard API rejects',
            { writeText: jest.fn(() => Promise.reject(new Error('denied'))) },
            true,
            'copied',
            1,
        ],
        ['the Clipboard API is absent and the fallback fails', undefined, false, 'unavailable', 1],
        [
            'the Clipboard API rejects and the fallback fails',
            { writeText: jest.fn(() => Promise.reject(new Error('denied'))) },
            false,
            'failed',
            1,
        ],
    ])('returns %s -> %s', async (_description, clipboard, fallbackWorks, expected, expectedFallbackCalls) => {
        setClipboard(clipboard)
        if (!fallbackWorks) {
            execCommand.mockImplementation(() => {
                throw new Error('not allowed')
            })
        }

        await expect(writeToClipboard('some text')).resolves.toBe(expected)
        expect(execCommand).toHaveBeenCalledTimes(expectedFallbackCalls)
    })

    // Browsers do not all accept text/html in a ClipboardItem, so a rich copy that a browser refuses has
    // to land as plain text rather than reporting failure.
    it.each([
        ['lands', () => Promise.resolve(), 0],
        ['is refused', () => Promise.reject(new Error('unsupported')), 1],
    ])('writes plain text when the rich write %s', async (_description, write, expectedWriteTextCalls) => {
        Object.defineProperty(globalThis, 'ClipboardItem', { value: class {}, configurable: true })
        const writeText = jest.fn(() => Promise.resolve())
        setClipboard({ write: jest.fn(write), writeText })

        await expect(writeToClipboard('some text', '<b>some text</b>')).resolves.toBe('copied')
        expect(writeText).toHaveBeenCalledTimes(expectedWriteTextCalls)
    })
})
