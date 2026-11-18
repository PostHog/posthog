import posthog from 'posthog-js'

import { ApiError } from 'lib/api-error'

import { terminalNetplayMailboxRetrieve, terminalNetplaySignalCreate } from '~/generated/core/api'
import type { TerminalNetplayReceivedSignalApi } from '~/generated/core/api.schemas'

// Doom's network module in PostHog/terminal-assets sends SLIP frames over the guest's third serial port.
// The first byte names the peer: guest frames name the destination, and host frames name the source.
const SLIP_END = 0xc0
const SLIP_ESC = 0xdb
const SLIP_ESC_END = 0xdc
const SLIP_ESC_ESC = 0xdd
const HOST_PEER = 0
const CONTROL_PEER = 255
const MAX_FRAME = 1500

const ROOM_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
const ICE_SERVERS: RTCIceServer[] = [{ urls: 'stun:stun.cloudflare.com:3478' }]
const HOST_POLL_MS = 1000
const JOIN_POLL_MS = 500
const JOIN_TIMEOUT_MS = 20_000
const GATHER_TIMEOUT_MS = 3000
const MAX_PENDING_PEERS = 16

interface HostLobby {
    room: string
    token: string
    game: AbortSignal
    signal: AbortSignal
    peers: Map<string, number>
    pending: Set<string>
}

export function encodeFrame(peer: number, payload: Uint8Array): Uint8Array {
    const bytes = [SLIP_END]
    for (const byte of [peer, ...payload]) {
        if (byte === SLIP_END) {
            bytes.push(SLIP_ESC, SLIP_ESC_END)
        } else if (byte === SLIP_ESC) {
            bytes.push(SLIP_ESC, SLIP_ESC_ESC)
        } else {
            bytes.push(byte)
        }
    }
    bytes.push(SLIP_END)
    return Uint8Array.from(bytes)
}

export class FrameDecoder {
    private frame: number[] = []
    private escaped = false
    private overflow = false

    push(byte: number): Uint8Array | null {
        if (byte === SLIP_END) {
            const frame = this.overflow || !this.frame.length ? null : Uint8Array.from(this.frame)
            this.frame = []
            this.escaped = false
            this.overflow = false
            return frame
        }
        if (this.escaped) {
            byte = byte === SLIP_ESC_END ? SLIP_END : byte === SLIP_ESC_ESC ? SLIP_ESC : byte
            this.escaped = false
        } else if (byte === SLIP_ESC) {
            this.escaped = true
            return null
        }
        if (this.frame.length <= MAX_FRAME) {
            this.frame.push(byte)
        } else {
            this.overflow = true
        }
        return null
    }
}

function randomCode(alphabet: string, length: number): string {
    return Array.from(
        crypto.getRandomValues(new Uint8Array(length)),
        (value) => alphabet[value % alphabet.length]
    ).join('')
}

function sleep(ms: number, signal: AbortSignal): Promise<void> {
    return new Promise((resolve) => {
        if (signal.aborted) {
            resolve()
            return
        }
        const timer = setTimeout(done, ms)
        signal.addEventListener('abort', done, { once: true })
        function done(): void {
            clearTimeout(timer)
            signal.removeEventListener('abort', done)
            resolve()
        }
    })
}

// Sending complete descriptions avoids a second signaling round trip for each ICE candidate.
function gathered(connection: RTCPeerConnection, signal: AbortSignal): Promise<void> {
    return new Promise((resolve) => {
        const timer = setTimeout(done, GATHER_TIMEOUT_MS)
        connection.addEventListener('icegatheringstatechange', check)
        signal.addEventListener('abort', done, { once: true })
        check()
        function check(): void {
            if (signal.aborted || connection.iceGatheringState === 'complete') {
                done()
            }
        }
        function done(): void {
            clearTimeout(timer)
            connection.removeEventListener('icegatheringstatechange', check)
            signal.removeEventListener('abort', done)
            resolve()
        }
    })
}

function opened(channel: RTCDataChannel, timeout: number, signal: AbortSignal): Promise<boolean> {
    return new Promise((resolve) => {
        if (signal.aborted) {
            resolve(false)
            return
        }
        if (channel.readyState === 'open') {
            resolve(true)
            return
        }
        const timer = setTimeout(() => done(false), timeout)
        const open = (): void => done(true)
        const close = (): void => done(false)
        channel.addEventListener('open', open)
        channel.addEventListener('close', close)
        signal.addEventListener('abort', close, { once: true })
        function done(result: boolean): void {
            clearTimeout(timer)
            channel.removeEventListener('open', open)
            channel.removeEventListener('close', close)
            signal.removeEventListener('abort', close)
            resolve(result)
        }
    })
}

class NetplayError extends Error {}

/** Relays Doom network frames between this terminal's VM and other players' browsers over WebRTC. */
export class TerminalNetplay {
    private decoder = new FrameDecoder()
    private encoder = new TextEncoder()
    private send?: (bytes: Uint8Array) => void
    private game?: AbortController
    private lobby?: AbortController
    private channels = new Map<number, RTCDataChannel>()

    constructor(
        private projectId: string,
        signal: AbortSignal
    ) {
        signal.addEventListener('abort', () => this.endGame(), { once: true })
    }

    attach(send: (bytes: Uint8Array) => void): void {
        this.send = send
    }

    receive(byte: number): void {
        const frame = this.decoder.push(byte)
        if (!frame) {
            return
        }
        if (frame[0] === CONTROL_PEER) {
            this.control(new TextDecoder().decode(frame.subarray(1)))
            return
        }
        const channel = this.channels.get(frame[0])
        if (channel?.readyState === 'open') {
            channel.send(frame.slice(1))
        }
    }

    private control(message: string): void {
        if (message === 'host') {
            void this.host(this.newGame())
        } else if (message.startsWith('join ')) {
            void this.join(message.slice(5).toUpperCase(), this.newGame())
        } else if (message === 'launched') {
            // Doom accepts no players after launch, so the room can expire.
            this.lobby?.abort()
        }
    }

    private reply(message: string): void {
        this.send?.(encodeFrame(CONTROL_PEER, this.encoder.encode(message)))
    }

    private newGame(): AbortSignal {
        this.endGame()
        this.game = new AbortController()
        return this.game.signal
    }

    private endGame(): void {
        this.lobby?.abort()
        this.game?.abort()
        this.channels.clear()
    }

    private connect(
        peer: number,
        game: AbortSignal
    ): { connection: RTCPeerConnection; channel: RTCDataChannel; close: () => void } {
        const connection = new RTCPeerConnection({ iceServers: ICE_SERVERS })
        // Doom resends lost packets itself, so late packets are worse than lost ones.
        const channel = connection.createDataChannel('doom', {
            negotiated: true,
            id: 0,
            ordered: false,
            maxRetransmits: 0,
        })
        channel.binaryType = 'arraybuffer'
        let closed = false
        channel.addEventListener('message', ({ data }: MessageEvent<ArrayBuffer>) => {
            if (!closed && !game.aborted && data.byteLength <= MAX_FRAME) {
                this.send?.(encodeFrame(peer, new Uint8Array(data)))
            }
        })
        const close = (): void => {
            if (closed) {
                return
            }
            closed = true
            game.removeEventListener('abort', close)
            channel.removeEventListener('close', close)
            connection.close()
            if (this.channels.get(peer) === channel) {
                this.channels.delete(peer)
            }
        }
        game.addEventListener('abort', close, { once: true })
        channel.addEventListener('close', close, { once: true })
        this.channels.set(peer, channel)
        return { connection, channel, close }
    }

    private async host(game: AbortSignal): Promise<void> {
        const room = randomCode(ROOM_ALPHABET, 6)
        const lobby = (this.lobby = new AbortController())
        const signal = lobby.signal
        const token = randomCode('0123456789abcdef', 64)
        const state: HostLobby = { room, token, game, signal, peers: new Map(), pending: new Set() }
        let announced = false
        while (!signal.aborted) {
            try {
                const { signals } = await terminalNetplayMailboxRetrieve(
                    this.projectId,
                    { room, peer: 'host' },
                    { signal, headers: { 'X-Terminal-Netplay-Token': token } }
                )
                if (signal.aborted) {
                    return
                }
                if (!announced) {
                    announced = true
                    this.reply(`room ${room}`)
                    posthog.capture('terminal deathmatch hosted')
                }
                this.acceptOffers(state, signals)
            } catch (error) {
                if (signal.aborted) {
                    return
                }
                if (!announced) {
                    this.reply(`error ${this.describe(error, 'Could not open a deathmatch room. Try again.')}`)
                    return
                }
            }
            await sleep(HOST_POLL_MS, signal)
        }
    }

    private acceptOffers(lobby: HostLobby, signals: TerminalNetplayReceivedSignalApi[]): void {
        for (const { sender, description } of signals) {
            if (description.type !== 'offer' || lobby.peers.has(sender) || lobby.pending.size >= MAX_PENDING_PEERS) {
                continue
            }
            const allocated = new Set(lobby.peers.values())
            let peer = HOST_PEER + 1
            while (allocated.has(peer)) {
                peer++
            }
            if (peer < CONTROL_PEER) {
                lobby.peers.set(sender, peer)
                lobby.pending.add(sender)
                void this.accept(lobby, sender, description.sdp, peer)
            }
        }
    }

    private async accept(lobby: HostLobby, sender: string, sdp: string, peer: number): Promise<void> {
        const negotiation = new AbortController()
        const signal = negotiation.signal
        const abort = (): void => negotiation.abort()
        const timeout = setTimeout(abort, JOIN_TIMEOUT_MS)
        lobby.signal.addEventListener('abort', abort, { once: true })
        let close: (() => void) | undefined
        let connected = false
        try {
            const client = this.connect(peer, lobby.game)
            close = client.close
            signal.addEventListener('abort', client.close, { once: true })
            const { connection, channel } = client
            await connection.setRemoteDescription({ type: 'offer', sdp })
            if (signal.aborted) {
                return
            }
            await connection.setLocalDescription()
            await gathered(connection, signal)
            if (signal.aborted || !connection.localDescription) {
                return
            }
            await terminalNetplaySignalCreate(
                this.projectId,
                {
                    room: lobby.room,
                    sender: 'host',
                    recipient: sender,
                    description: { type: 'answer', sdp: connection.localDescription.sdp },
                },
                { signal, headers: { 'X-Terminal-Netplay-Token': lobby.token } }
            )
            connected = await opened(channel, JOIN_TIMEOUT_MS, signal)
        } catch {
            // The joining player reports the failure when the answer does not arrive.
        } finally {
            clearTimeout(timeout)
            lobby.signal.removeEventListener('abort', abort)
            if (close) {
                signal.removeEventListener('abort', close)
            }
            lobby.pending.delete(sender)
            if (!connected) {
                close?.()
                lobby.peers.delete(sender)
            }
        }
    }

    private async waitForAnswer(
        room: string,
        peer: string,
        token: string,
        deadline: number,
        game: AbortSignal
    ): Promise<string | undefined> {
        while (!game.aborted) {
            if (Date.now() > deadline) {
                throw new NetplayError('The host did not answer. Check the room code and try again.')
            }
            await sleep(JOIN_POLL_MS, game)
            if (game.aborted) {
                return
            }
            const { signals } = await terminalNetplayMailboxRetrieve(
                this.projectId,
                { room, peer },
                { signal: game, headers: { 'X-Terminal-Netplay-Token': token } }
            )
            const answer = signals.find(({ sender, description }) => sender === 'host' && description.type === 'answer')
            if (answer) {
                return answer.description.sdp
            }
        }
    }

    private async join(room: string, game: AbortSignal): Promise<void> {
        const id = randomCode('abcdefghijklmnopqrstuvwxyz0123456789', 16)
        const token = randomCode('0123456789abcdef', 64)
        const deadline = Date.now() + JOIN_TIMEOUT_MS
        let close: (() => void) | undefined
        let connected = false
        try {
            const client = this.connect(HOST_PEER, game)
            close = client.close
            const { connection, channel } = client
            await connection.setLocalDescription()
            await gathered(connection, game)
            if (game.aborted || !connection.localDescription) {
                return
            }
            await terminalNetplaySignalCreate(
                this.projectId,
                {
                    room,
                    sender: id,
                    recipient: 'host',
                    description: { type: 'offer', sdp: connection.localDescription.sdp },
                },
                { signal: game, headers: { 'X-Terminal-Netplay-Token': token } }
            )
            const answer = await this.waitForAnswer(room, id, token, deadline, game)
            if (game.aborted || !answer) {
                return
            }
            await connection.setRemoteDescription({ type: 'answer', sdp: answer })
            connected = await opened(channel, Math.max(deadline - Date.now(), 5000), game)
            if (!connected) {
                throw new NetplayError(
                    'Could not connect to the host. A firewall or VPN may block peer-to-peer connections.'
                )
            }
            if (!game.aborted) {
                this.reply('joined')
                posthog.capture('terminal deathmatch joined', { success: true })
            }
        } catch (error) {
            if (!game.aborted) {
                this.reply(`error ${this.describe(error, 'Could not join the deathmatch. Try again.')}`)
                posthog.capture('terminal deathmatch joined', { success: false })
            }
        } finally {
            if (!connected) {
                close?.()
            }
        }
    }

    private describe(error: unknown, fallback: string): string {
        if (error instanceof NetplayError) {
            return error.message
        }
        if (error instanceof ApiError && (error.status === 404 || error.status === 429) && error.detail) {
            return error.detail
        }
        return fallback
    }
}
