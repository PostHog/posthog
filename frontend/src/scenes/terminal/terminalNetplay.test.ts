import { ApiError } from 'lib/api-error'

import { terminalNetplayMailboxRetrieve, terminalNetplaySignalCreate } from '~/generated/core/api'

import { FrameDecoder, TerminalNetplay, encodeFrame } from './terminalNetplay'

jest.mock('~/generated/core/api', () => ({
    terminalNetplayMailboxRetrieve: jest.fn(),
    terminalNetplaySignalCreate: jest.fn(),
}))

class FakeChannel extends EventTarget {
    readyState: RTCDataChannelState = 'open'
    binaryType = 'blob'
    send = jest.fn()
}

class FakeConnection extends EventTarget {
    static created: FakeConnection[] = []
    static configure?: (connection: FakeConnection) => void
    iceGatheringState: RTCIceGatheringState = 'complete'
    localDescription: { sdp: string } | null = null
    channel = new FakeChannel()
    createDataChannel = jest.fn(() => this.channel)
    setRemoteDescription = jest.fn(async () => {})
    setLocalDescription = jest.fn(async () => {
        this.localDescription = { sdp: `local sdp ${FakeConnection.created.indexOf(this)}` }
    })
    close = jest.fn()

    constructor() {
        super()
        FakeConnection.created.push(this)
        FakeConnection.configure?.(this)
    }
}

describe('terminal Doom netplay', () => {
    const mailbox = terminalNetplayMailboxRetrieve as jest.Mock
    const signal = terminalNetplaySignalCreate as jest.Mock
    const originalConnection = globalThis.RTCPeerConnection
    let session: AbortController
    let netplay: TerminalNetplay
    let guest: { peer: number; text: string; bytes: number[] }[]

    const fromGuest = (peer: number, payload: string | number[]): void => {
        const bytes = typeof payload === 'string' ? new TextEncoder().encode(payload) : Uint8Array.from(payload)
        for (const byte of encodeFrame(peer, bytes)) {
            netplay.receive(byte)
        }
    }

    beforeEach(() => {
        jest.useFakeTimers()
        FakeConnection.created = []
        FakeConnection.configure = undefined
        globalThis.RTCPeerConnection = FakeConnection as unknown as typeof RTCPeerConnection
        mailbox.mockReset().mockResolvedValue({ signals: [] })
        signal.mockReset().mockResolvedValue(undefined)
        session = new AbortController()
        netplay = new TerminalNetplay('42', session.signal)
        guest = []
        const decoder = new FrameDecoder()
        netplay.attach((bytes) => {
            for (const byte of bytes) {
                const frame = decoder.push(byte)
                if (frame) {
                    const payload = Array.from(frame.subarray(1))
                    guest.push({ peer: frame[0], text: new TextDecoder().decode(frame.slice(1)), bytes: payload })
                }
            }
        })
    })

    afterEach(() => {
        session.abort()
        jest.useRealTimers()
        globalThis.RTCPeerConnection = originalConnection
    })

    it('keeps SLIP escape bytes intact in both directions', () => {
        const decoder = new FrameDecoder()
        const frames = [...encodeFrame(7, Uint8Array.from([0xc0, 1, 0xdb, 0xdc]))]
            .map((byte) => decoder.push(byte))
            .filter(Boolean)

        expect(frames).toEqual([Uint8Array.from([7, 0xc0, 1, 0xdb, 0xdc])])
    })

    it('hosts a room, answers an offer, and relays packets until the game launches', async () => {
        fromGuest(255, 'host')
        await jest.advanceTimersByTimeAsync(0)

        expect(guest).toEqual([
            { peer: 255, text: expect.stringMatching(/^room [A-Z0-9]{6}$/), bytes: expect.any(Array) },
        ])
        const room = guest[0].text.slice(5)
        expect(mailbox).toHaveBeenLastCalledWith('42', { room, peer: 'host' }, expect.anything())

        mailbox.mockResolvedValueOnce({ signals: [{ sender: 'abc', description: { type: 'offer', sdp: 'offer' } }] })
        await jest.advanceTimersByTimeAsync(1000)

        const [connection] = FakeConnection.created
        expect(connection.setRemoteDescription).toHaveBeenCalledWith({ type: 'offer', sdp: 'offer' })
        expect(signal).toHaveBeenCalledWith(
            '42',
            { room, sender: 'host', recipient: 'abc', description: { type: 'answer', sdp: 'local sdp 0' } },
            expect.anything()
        )
        expect(mailbox.mock.calls[0][2].headers['X-Terminal-Netplay-Token']).toMatch(/^[a-f0-9]{64}$/)
        expect(signal.mock.calls[0][2].headers).toEqual(mailbox.mock.calls[0][2].headers)

        connection.channel.dispatchEvent(new MessageEvent('message', { data: Uint8Array.from([1, 2, 3]).buffer }))
        fromGuest(1, [9, 8])
        fromGuest(2, [7])

        expect(guest[1]).toEqual({ peer: 1, text: expect.any(String), bytes: [1, 2, 3] })
        expect(connection.channel.send).toHaveBeenCalledTimes(1)
        expect(connection.channel.send).toHaveBeenCalledWith(Uint8Array.from([9, 8]))

        fromGuest(255, 'launched')
        const polls = mailbox.mock.calls.length
        await jest.advanceTimersByTimeAsync(5000)
        expect(mailbox).toHaveBeenCalledTimes(polls)
        expect(connection.close).not.toHaveBeenCalled()
    })

    it('joins a room and relays packets with the host as peer 0', async () => {
        mailbox.mockResolvedValueOnce({ signals: [{ sender: 'host', description: { type: 'answer', sdp: 'answer' } }] })

        fromGuest(255, 'join abc123')
        await jest.advanceTimersByTimeAsync(500)

        const [connection] = FakeConnection.created
        expect(signal).toHaveBeenCalledWith(
            '42',
            expect.objectContaining({
                room: 'ABC123',
                recipient: 'host',
                description: { type: 'offer', sdp: 'local sdp 0' },
            }),
            expect.anything()
        )
        expect(connection.setRemoteDescription).toHaveBeenCalledWith({ type: 'answer', sdp: 'answer' })
        expect(guest).toEqual([{ peer: 255, text: 'joined', bytes: expect.any(Array) }])
        expect(signal.mock.calls[0][2].headers['X-Terminal-Netplay-Token']).toMatch(/^[a-f0-9]{64}$/)
        expect(mailbox.mock.calls[0][2].headers).toEqual(signal.mock.calls[0][2].headers)

        connection.channel.dispatchEvent(new MessageEvent('message', { data: Uint8Array.from([4]).buffer }))
        fromGuest(0, [5])

        expect(guest[1].peer).toBe(0)
        expect(guest[1].bytes).toEqual([4])
        expect(connection.channel.send).toHaveBeenCalledWith(Uint8Array.from([5]))
    })

    it('ignores repeated offers from the same player', async () => {
        const offer = { sender: 'abc', description: { type: 'offer', sdp: 'offer' } }
        mailbox.mockResolvedValue({ signals: [offer, offer] })

        fromGuest(255, 'host')
        await jest.advanceTimersByTimeAsync(2000)

        expect(FakeConnection.created).toHaveLength(1)
        expect(signal).toHaveBeenCalledTimes(1)
    })

    it('closes rejected offers and reuses their peer slots', async () => {
        FakeConnection.configure = (connection) => {
            connection.setRemoteDescription.mockRejectedValue(new Error('Invalid SDP'))
        }
        mailbox.mockResolvedValueOnce({
            signals: ['a', 'b', 'c'].map((sender) => ({ sender, description: { type: 'offer', sdp: 'invalid' } })),
        })
        fromGuest(255, 'host')
        await jest.advanceTimersByTimeAsync(0)
        for (const connection of FakeConnection.created) {
            expect(connection.close).toHaveBeenCalledTimes(1)
        }
        expect(signal).not.toHaveBeenCalled()

        FakeConnection.configure = undefined
        mailbox.mockResolvedValueOnce({ signals: [{ sender: 'a', description: { type: 'offer', sdp: 'valid' } }] })
        await jest.advanceTimersByTimeAsync(1000)
        const connection = FakeConnection.created[3]
        fromGuest(1, [7])

        expect(connection.channel.send).toHaveBeenCalledWith(Uint8Array.from([7]))
        expect(signal).toHaveBeenCalledTimes(1)
    })

    it('bounds pending connections and releases them when the channel never opens', async () => {
        FakeConnection.configure = (connection) => {
            connection.channel.readyState = 'connecting'
        }
        mailbox.mockResolvedValueOnce({
            signals: Array.from({ length: 17 }, (_, index) => ({
                sender: `player${index}`,
                description: { type: 'offer', sdp: 'offer' },
            })),
        })
        fromGuest(255, 'host')
        await jest.advanceTimersByTimeAsync(0)
        expect(FakeConnection.created).toHaveLength(16)

        await jest.advanceTimersByTimeAsync(20_000)
        for (const connection of FakeConnection.created) {
            expect(connection.close).toHaveBeenCalledTimes(1)
        }
        FakeConnection.configure = undefined
        mailbox.mockResolvedValueOnce({
            signals: [{ sender: 'player0', description: { type: 'offer', sdp: 'retry' } }],
        })
        await jest.advanceTimersByTimeAsync(1000)
        fromGuest(1, [7])
        expect(FakeConnection.created[16].channel.send).toHaveBeenCalledWith(Uint8Array.from([7]))
    })

    it('ignores answers from anyone other than the host', async () => {
        mailbox
            .mockResolvedValueOnce({ signals: [{ sender: 'other', description: { type: 'answer', sdp: 'forged' } }] })
            .mockResolvedValueOnce({ signals: [{ sender: 'host', description: { type: 'answer', sdp: 'answer' } }] })
        fromGuest(255, 'join ABC123')
        await jest.advanceTimersByTimeAsync(500)
        const [connection] = FakeConnection.created
        expect(connection.setRemoteDescription).not.toHaveBeenCalled()

        await jest.advanceTimersByTimeAsync(500)
        expect(connection.setRemoteDescription).toHaveBeenCalledWith({ type: 'answer', sdp: 'answer' })
    })

    it('discards a mailbox response that arrives after the session ends', async () => {
        let respond!: (value: unknown) => void
        mailbox.mockReturnValueOnce(new Promise((resolve) => (respond = resolve)))
        fromGuest(255, 'host')
        session.abort()
        respond({ signals: [{ sender: 'abc', description: { type: 'offer', sdp: 'offer' } }] })
        await jest.advanceTimersByTimeAsync(0)

        expect(FakeConnection.created).toHaveLength(0)
        expect(guest).toEqual([])
    })

    it('closes pending negotiations when the host launches', async () => {
        FakeConnection.configure = (connection) => {
            connection.channel.readyState = 'connecting'
        }
        mailbox.mockResolvedValueOnce({ signals: [{ sender: 'abc', description: { type: 'offer', sdp: 'offer' } }] })
        fromGuest(255, 'host')
        await jest.advanceTimersByTimeAsync(0)
        fromGuest(255, 'launched')
        await jest.advanceTimersByTimeAsync(0)

        expect(FakeConnection.created[0].close).toHaveBeenCalledTimes(1)
    })

    it.each([
        [
            'an unknown room',
            () =>
                signal.mockRejectedValueOnce(
                    new ApiError('Not found', 404, undefined, { detail: 'No deathmatch room has this code.' })
                ),
            'error No deathmatch room has this code.',
        ],
        [
            'too many connection attempts',
            () =>
                signal.mockRejectedValueOnce(
                    new ApiError('Throttled', 429, undefined, { detail: 'Try again in 30 seconds.' })
                ),
            'error Try again in 30 seconds.',
        ],
        ['a host that never answers', () => {}, 'error The host did not answer. Check the room code and try again.'],
    ])('reports %s to Doom', async (_name, setup, message) => {
        setup()

        fromGuest(255, 'join ABC123')
        await jest.advanceTimersByTimeAsync(30_000)

        expect(guest).toEqual([{ peer: 255, text: message, bytes: expect.any(Array) }])
        expect(FakeConnection.created[0].close).toHaveBeenCalledTimes(1)
    })
})
