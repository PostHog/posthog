import { z } from 'zod'

const configurationSchema = z
    .object({
        url: z
            .string()
            .url()
            .refine((value) => {
                const url = new URL(value)
                return (
                    (url.protocol === 'wss:' ||
                        (url.protocol === 'ws:' && ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname))) &&
                    !url.username &&
                    !url.password &&
                    !url.search &&
                    !url.hash &&
                    url.pathname === '/netplay'
                )
            }),
        token: z.string().min(1).max(2048),
    })
    .strict()

export const NETPLAY_HELP = `ph netplay: configure a game relay for Doom

Read settings from a file:
  ph netplay configure --json @/tmp/relay.json
Or from stdin (finish with Ctrl+D):
  ph netplay configure --json -
Check the mode without showing credentials:
  ph netplay status
Restore direct connections for the next game:
  ph netplay clear

JSON format:
  {
    "url": "wss://relay.example.com/netplay",
    "token": "temporary-access-token"
  }

Ask the relay operator for a temporary token.
Never enter the relay's signing key.
Both players configure the same relay first,
using tokens for the same group.
Host: doom -server -deathmatch
Join: doom -connect <code>
The host must stay connected.

Ask your PostHog admin to allow the relay URL.
Settings apply to the next game and clear when
this terminal stops or the page reloads.
Keep credential files in /tmp, then delete them.
Avoid tokens in shell history.
`

export class TerminalRelay {
    private configuration?: z.infer<typeof configurationSchema>
    private socket?: WebSocket
    private hosting = false

    constructor(
        private session: AbortSignal,
        private reply: (message: string) => void,
        private packet: (peer: number, bytes: Uint8Array) => void
    ) {
        session.addEventListener(
            'abort',
            () => {
                this.configuration = undefined
            },
            { once: true }
        )
    }

    get configured(): boolean {
        return !!this.configuration
    }

    get active(): boolean {
        return !!this.socket
    }

    command(argv: string[]): string {
        if (this.session.aborted) {
            throw new Error('The terminal stopped. Start it again before configuring netplay.')
        }
        const [action = 'help', ...rest] = argv
        if (['help', '--help'].includes(action) && !rest.length) {
            return NETPLAY_HELP
        }
        if (action === 'status' && !rest.length) {
            return this.configuration
                ? 'Game relay configured. Applies to the next game.'
                : 'No game relay configured. Using direct peer-to-peer connections.'
        }
        if (action === 'clear' && !rest.length) {
            this.configuration = undefined
            return 'Game relay cleared. The next game will use direct peer-to-peer connections.'
        }
        if (action !== 'configure' || rest.length !== 2 || rest[0] !== '--json') {
            throw new Error('Run ph netplay help for usage.')
        }
        try {
            this.configuration = configurationSchema.parse(JSON.parse(rest[1]))
        } catch {
            // Parser errors can include the access token.
            throw new Error('Invalid relay configuration. Run ph netplay help for the JSON format.')
        }
        return this.command(['status'])
    }

    start(room: string | undefined, game: AbortSignal): void {
        if (!this.configuration || game.aborted || this.session.aborted) {
            return
        }
        const configuration = this.configuration
        let socket: WebSocket
        try {
            socket = new WebSocket(configuration.url)
        } catch {
            this.reply('error Could not open the relay. Check its URL and PostHog security policy.')
            return
        }
        this.socket = socket
        this.hosting = !room
        socket.binaryType = 'arraybuffer'
        let ready = false
        let finished = false
        const timeout = setTimeout(() => fail('The relay did not answer. Check its URL and try again.'), 10_000)
        const stop = (): void => {
            if (finished) {
                return
            }
            finished = true
            clearTimeout(timeout)
            game.removeEventListener('abort', stop)
            this.session.removeEventListener('abort', stop)
            socket.onopen = socket.onmessage = socket.onerror = socket.onclose = null
            socket.close()
            if (this.socket === socket) {
                this.socket = undefined
            }
        }
        const fail = (message: string): void => {
            if (!finished && !game.aborted && !this.session.aborted) {
                this.reply(`error ${message}`)
            }
            stop()
        }
        game.addEventListener('abort', stop, { once: true })
        this.session.addEventListener('abort', stop, { once: true })
        socket.onopen = () =>
            socket.send(JSON.stringify({ action: room ? 'join' : 'host', room, token: configuration.token }))
        socket.onmessage = ({ data }) => {
            if (data instanceof ArrayBuffer) {
                const bytes = new Uint8Array(data)
                if (!ready || bytes.length < 2 || bytes.length > 1501 || bytes[0] >= 4) {
                    fail('The relay sent an invalid game packet.')
                    return
                }
                this.packet(bytes[0], bytes.slice(1))
                return
            }
            try {
                if (ready || typeof data !== 'string' || data.length > 256) {
                    throw new Error()
                }
                const message = JSON.parse(data)
                if (
                    (!room && message.type === 'room' && /^[A-Z0-9]{6}$/.test(message.room)) ||
                    (room && message.type === 'joined' && message.room === room)
                ) {
                    ready = true
                    clearTimeout(timeout)
                    this.reply(room ? 'joined' : `room ${message.room}`)
                } else {
                    throw new Error()
                }
            } catch {
                fail('The relay sent an invalid response.')
            }
        }
        socket.onerror = () => fail('Could not connect to the relay. Check its URL and PostHog security policy.')
        socket.onclose = ({ code }) =>
            fail(
                code === 1008
                    ? 'The relay refused or expired this connection. Check the token, room code, and room limits.'
                    : 'The relay connection closed. The host may have left. Start a new game to reconnect.'
            )
    }

    send(peer: number, payload: Uint8Array): void {
        if (this.socket?.readyState === WebSocket.OPEN && this.socket.bufferedAmount < 65536) {
            this.socket.send(Uint8Array.from([peer, ...payload]))
        }
    }

    launched(): void {
        if (this.hosting && this.socket?.readyState === WebSocket.OPEN) {
            this.socket.send('launched')
        }
    }
}
