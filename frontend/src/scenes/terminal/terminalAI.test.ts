import { waitFor } from '@testing-library/react'
import { ReadableStream } from 'node:stream/web'

import { TerminalAI } from './terminalAI'
import { TerminalFile, TerminalFilesystem } from './terminalFilesystem'

describe('terminal AI bridge', () => {
    const originalFetch = globalThis.fetch
    const originalAny = Object.getOwnPropertyDescriptor(AbortSignal, 'any')
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
        jest.useRealTimers()
        globalThis.fetch = originalFetch
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
        if (action === 'cancel') {
            await expect(request('retry')).rejects.toMatchObject({ errno: 16 })
        }
        stream.close()
        await waitFor(async () => expect((await read()).done).toBe(true))
        if (action === 'cancel') {
            await request('retry')
            expect(await read()).toMatchObject({ id: 'retry', done: false })
            stream.close()
            await waitFor(async () => expect((await read()).done).toBe(true))
        }
    })

    it('keeps active generations alive and aborts after 120 seconds without a chunk', async () => {
        jest.useFakeTimers()
        await request('long-running')
        const signal = (fetch as jest.Mock).mock.calls[0][1].signal as AbortSignal
        await jest.advanceTimersByTimeAsync(119_000)
        stream.enqueue(encoder.encode('data: first\n\n'))
        await jest.advanceTimersByTimeAsync(119_000)
        expect(signal.aborted).toBe(false)
        expect(await read()).toMatchObject({ body: 'data: first\n\n', done: false })
        await jest.advanceTimersByTimeAsync(1000)
        expect(signal.aborted).toBe(true)
        stream.close()
        await jest.advanceTimersByTimeAsync(0)
        expect((await read()).done).toBe(true)
        expect(jest.getTimerCount()).toBe(0)
    })

    it('reports a failed request and allows a retry', async () => {
        ;(fetch as jest.Mock).mockRejectedValueOnce(new Error('Connection failed'))
        await request('failed')
        expect(await read()).toMatchObject({ id: 'failed', error: 'Connection failed', done: true })
        await request('retry')
        expect(await read()).toMatchObject({ id: 'retry', status: 200, done: false })
        stream.close()
        await waitFor(async () => expect((await read()).done).toBe(true))
    })
})
