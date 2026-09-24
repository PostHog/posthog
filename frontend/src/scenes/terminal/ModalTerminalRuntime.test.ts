import { ApiError } from 'lib/api-error'

import { terminalCreate, terminalDestroy } from '~/generated/core/api'

import { ModalTerminalRuntime } from './ModalTerminalRuntime'

jest.mock('~/generated/core/api', () => ({ terminalCreate: jest.fn(), terminalDestroy: jest.fn() }))

describe('ModalTerminalRuntime', () => {
    const session = {
        id: 'session-1',
        url: 'https://terminal.example.com',
        token: 'fake-connect-token',
        sandbox_size: 'small' as const,
    }

    beforeEach(() => {
        jest.clearAllMocks()
        jest.mocked(terminalDestroy).mockResolvedValue(undefined)
    })

    afterEach(() => jest.restoreAllMocks())

    it('connects with a scoped token and transports input, Unicode output, and dimensions', async () => {
        jest.mocked(terminalCreate).mockResolvedValue(session)
        const socket = {
            readyState: WebSocket.OPEN,
            send: jest.fn(),
            close: jest.fn(),
            onopen: null as (() => void) | null,
            onmessage: null as ((event: { data: ArrayBuffer }) => void) | null,
        }
        const connect = jest.spyOn(window, 'WebSocket').mockImplementation(() => socket as unknown as WebSocket)
        Object.assign(connect, { OPEN: socket.readyState })
        const output = jest.fn()
        const runtime = new ModalTerminalRuntime('2', output, jest.fn())
        runtime.resize(100, 35)
        const started = runtime.start('small')
        await waitFor(() => expect(socket.onopen).not.toBeNull())
        socket.onopen?.()
        await started
        const url = new URL(String(connect.mock.calls[0][0]))
        expect(url.protocol).toBe('wss:')
        expect(url.pathname).toBe('/terminal')
        expect(url.searchParams.get('_modal_connect_token')).toBe(session.token)
        expect(JSON.parse(socket.send.mock.calls[0][0])).toEqual({ columns: 100, rows: 35 })
        const input = '😀'.repeat(9000)
        runtime.write(input)
        expect(
            socket.send.mock.calls
                .slice(1)
                .map(([message]) => JSON.parse(message))
                .join('')
        ).toBe(input)
        const bytes = new TextEncoder().encode('hello 😀')
        socket.onmessage?.({ data: bytes.slice(0, 8).buffer })
        socket.onmessage?.({ data: bytes.slice(8).buffer })
        expect(runtime.read()).toBe('hello 😀')
        expect(output).toHaveBeenCalledTimes(2)
        await runtime.stop()
        socket.onmessage?.({ data: bytes.buffer })
        expect(output).toHaveBeenCalledTimes(2)
        expect(socket.close).toHaveBeenCalled()
    })

    it('destroys a sandbox that finishes provisioning after Stop, without opening a socket', async () => {
        let finish!: (value: typeof session) => void
        jest.mocked(terminalCreate).mockReturnValue(
            new Promise((resolve) => {
                finish = resolve
            })
        )
        const socket = jest.spyOn(window, 'WebSocket')
        const runtime = new ModalTerminalRuntime('2', jest.fn(), jest.fn())
        const started = runtime.start('small')
        const stopped = runtime.stop()
        finish(session)
        await Promise.all([started, stopped])
        expect(terminalCreate).toHaveBeenCalledWith('2', { sandbox_size: 'small' })
        expect(socket).not.toHaveBeenCalled()
        expect(terminalDestroy).toHaveBeenCalledWith('2', 'session-1')
        await runtime.stop()
        expect(terminalDestroy).toHaveBeenCalledTimes(1)
        socket.mockRestore()
    })

    it.each([
        ['allows retrying a failed stop', new Error('Unavailable'), true],
        ['treats a session another tab replaced as stopped', new ApiError('Not found', 404), false],
    ])('%s without creating another sandbox', async (_, error, retries) => {
        jest.mocked(terminalCreate).mockResolvedValue(session)
        jest.mocked(terminalDestroy).mockRejectedValueOnce(error)
        const runtime = new ModalTerminalRuntime('2', jest.fn(), jest.fn())
        const started = runtime.start('small')
        if (retries) {
            await expect(runtime.stop()).rejects.toThrow(error.message)
        } else {
            await runtime.stop()
        }
        await started
        await runtime.stop()
        expect(terminalCreate).toHaveBeenCalledTimes(1)
        expect(terminalDestroy).toHaveBeenCalledTimes(retries ? 2 : 1)
    })
})
import { waitFor } from '@testing-library/react'
