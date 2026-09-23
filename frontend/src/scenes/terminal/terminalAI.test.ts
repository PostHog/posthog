import { waitFor } from '@testing-library/react'
import { ReadableStream } from 'node:stream/web'

import { TerminalAI } from './terminalAI'
import { TerminalFile, TerminalFilesystem } from './terminalFilesystem'

describe('terminal AI bridge', () => {
    const originalFetch = globalThis.fetch
    const originalAny = Object.getOwnPropertyDescriptor(AbortSignal, 'any')
    const originalTimeout = Object.getOwnPropertyDescriptor(AbortSignal, 'timeout')
    let filesystem: TerminalFilesystem
    let stream: ReadableStreamDefaultController<Uint8Array>
    let session: AbortController
    const encoder = new TextEncoder()
    const decoder = new TextDecoder()
    const file = (name: string): Promise<TerminalFile> =>
        filesystem.root.children!.get('.ai')!.children!.get(name)!.open!()
    const write = async (name: string, value: string): Promise<void> => (await file(name)).save!(encoder.encode(value))
    const request = (id: string): Promise<void> => write('request', JSON.stringify({ id, body: { messages: [] } }))
    const read = async (): Promise<{ id: string; body: string; done: boolean; error?: string }> =>
        JSON.parse(decoder.decode((await file('response')).bytes))

    beforeEach(() => {
        session = new AbortController()
        Object.defineProperty(AbortSignal, 'timeout', { configurable: true, value: () => new AbortController().signal })
        Object.defineProperty(AbortSignal, 'any', {
            configurable: true,
            value: (signals: AbortSignal[]) => {
                const controller = new AbortController()
                for (const signal of signals) {
                    signal.addEventListener('abort', () => controller.abort(), { once: true })
                }
                return controller.signal
            },
        })
        globalThis.fetch = jest.fn(async () => ({
            status: 200,
            body: new ReadableStream<Uint8Array>({ start: (controller) => (stream = controller) }),
        })) as jest.Mock
        filesystem = new TerminalFilesystem()
        new TerminalAI(filesystem, '42', session.signal)
    })

    afterEach(() => {
        globalThis.fetch = originalFetch
        if (originalTimeout) {
            Object.defineProperty(AbortSignal, 'timeout', originalTimeout)
        } else {
            delete (AbortSignal as Partial<typeof AbortSignal>).timeout
        }
        if (originalAny) {
            Object.defineProperty(AbortSignal, 'any', originalAny)
        } else {
            delete (AbortSignal as Partial<typeof AbortSignal>).any
        }
    })

    it('streams split Unicode without replaying chunks and uses only the current project', async () => {
        await request('first')
        const bytes = encoder.encode('data: "你好"\n\n')
        stream.enqueue(bytes.slice(0, 8))
        await Promise.resolve()
        const first = await read()
        stream.enqueue(bytes.slice(8))
        stream.close()
        const chunks = [first.body]
        await waitFor(async () => {
            const frame = await read()
            chunks.push(frame.body)
            expect(frame.done).toBe(true)
        })
        expect(chunks.join('')).toBe('data: "你好"\n\n')
        expect((await read()).body).toBe('')
        expect(fetch).toHaveBeenCalledWith(
            '/api/projects/42/terminal_ai/',
            expect.objectContaining({
                credentials: 'same-origin',
                redirect: 'error',
                method: 'POST',
            })
        )
    })

    it.each(['cancel', 'stop'])('aborts a generation on %s and refuses concurrent requests', async (action) => {
        await request('first')
        await expect(request('second')).rejects.toMatchObject({ errno: 16 })
        const signal = (fetch as jest.Mock).mock.calls[0][1].signal as AbortSignal
        if (action === 'cancel') {
            await write('cancel', 'second')
            expect(signal.aborted).toBe(false)
            await write('cancel', 'first')
        } else {
            session.abort()
        }
        expect(signal.aborted).toBe(true)
        stream.close()
    })

    it('reports a failed request and allows a retry', async () => {
        ;(fetch as jest.Mock).mockRejectedValueOnce(new Error('Connection failed'))
        await request('failed')
        expect(await read()).toMatchObject({ id: 'failed', error: 'Connection failed', done: true })
        await request('retry')
        expect(await read()).toMatchObject({ id: 'retry', status: 200, done: false })
        stream.close()
    })
})
