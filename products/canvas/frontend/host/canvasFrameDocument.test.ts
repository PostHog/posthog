import { readFileSync } from 'fs'
import { join } from 'path'

const WRAPPER_HTML = readFileSync(join(__dirname, '../../backend/frame/frame_document.html'), 'utf8')
const WRAPPER_SCRIPT = /<script>([\s\S]*?)<\/script>/.exec(WRAPPER_HTML)![1]
const ARTIFACT = `${window.location.origin}/canvas-artifacts`
const CHANNEL = 'posthog-canvas'

function runWrapper(src: string): HTMLIFrameElement | null {
    document.body.innerHTML = ''
    window.history.replaceState(null, '', `/#${new URLSearchParams({ src, theme: 'dark' })}`)
    window.eval(WRAPPER_SCRIPT)
    return document.querySelector('iframe')
}

describe('canvas frame wrapper document', () => {
    let received: any[]
    const onMessage = (event: MessageEvent): void => {
        received.push(event.data)
    }

    beforeEach(() => {
        received = []
        window.addEventListener('message', onMessage)
    })

    afterEach(() => {
        window.removeEventListener('message', onMessage)
    })

    test.each([
        ['an off-origin document', 'https://other.example/canvas-artifacts/token/index.html'],
        ['a path outside the canvas paths', `${window.location.origin}/api/projects/`],
        ['another wrapper', `${ARTIFACT}/frame/${'a'.repeat(64)}/index.html`],
        ['another wrapper with an encoded path', `${ARTIFACT}/%66rame/${'a'.repeat(64)}/index.html`],
        ['an empty address', ''],
    ])('refuses %s and tells the parent', async (_name, src) => {
        const frame = runWrapper(src)
        await new Promise((resolve) => setTimeout(resolve, 0))

        expect(frame).toBeNull()
        expect(received).toEqual([{ channel: CHANNEL, type: 'wrapper-error' }])
    })

    test('hands the port to the first canvas document only', async () => {
        const frame = runWrapper(`${ARTIFACT}/token/index.html`)!
        expect(frame.getAttribute('src')).toBe(`${ARTIFACT}/token/index.html`)
        const postToFrame = jest.fn()
        Object.defineProperty(frame, 'contentWindow', { value: { postMessage: postToFrame, close: jest.fn() } })
        const connect = (): void => {
            window.dispatchEvent(
                new MessageEvent('message', {
                    data: { channel: CHANNEL, type: 'connect' },
                    source: window,
                    ports: [{ close: jest.fn() } as unknown as MessagePort],
                })
            )
        }

        frame.dispatchEvent(new Event('load'))
        connect()
        expect(postToFrame).toHaveBeenCalledTimes(1)

        frame.dispatchEvent(new Event('load'))
        connect()
        expect(postToFrame).toHaveBeenCalledTimes(1)
        await new Promise((resolve) => setTimeout(resolve, 0))
        expect(received).toContainEqual({ channel: CHANNEL, type: 'navigated' })
    })

    test('a port that arrives after the frame navigated is dropped', () => {
        const frame = runWrapper(`${ARTIFACT}/token/index.html`)!
        const postToFrame = jest.fn()
        Object.defineProperty(frame, 'contentWindow', { value: { postMessage: postToFrame, close: jest.fn() } })

        frame.dispatchEvent(new Event('load'))
        frame.dispatchEvent(new Event('load'))
        window.dispatchEvent(
            new MessageEvent('message', {
                data: { channel: CHANNEL, type: 'connect' },
                source: window,
                ports: [{ close: jest.fn() } as unknown as MessagePort],
            })
        )

        expect(postToFrame).not.toHaveBeenCalled()
    })
})
