import * as net from 'net'

export type ReceivedSmtpEmail = {
    mailFrom: string
    rcptTo: string[]
    data: string
    auth?: { user: string; pass: string }
}

type OverridableCommand = 'MAIL' | 'RCPT' | 'DATA'

/**
 * A minimal in-process SMTP server speaking the real protocol over a real socket, so the
 * nodemailer send path is exercised end to end (connection pool, EHLO, AUTH, envelope, DATA,
 * MIME encoding) without any external network or actual email delivery.
 *
 * `respondWith` scripts error responses per command (e.g. `{ MAIL: '451 4.7.1 greylisted' }`)
 * to drive the retry/terminal classification paths.
 */
export class TestSmtpServer {
    public received: ReceivedSmtpEmail[] = []
    private server: net.Server
    private respondWith: Partial<Record<OverridableCommand, string>> = {}

    constructor(private port: number) {
        this.server = net.createServer((socket) => this.handleConnection(socket))
    }

    async start(): Promise<void> {
        await new Promise<void>((resolve, reject) => {
            this.server.once('error', reject)
            this.server.listen(this.port, '127.0.0.1', () => resolve())
        })
    }

    async stop(): Promise<void> {
        await new Promise<void>((resolve) => this.server.close(() => resolve()))
    }

    reset(): void {
        this.received = []
        this.respondWith = {}
    }

    setResponses(overrides: Partial<Record<OverridableCommand, string>>): void {
        this.respondWith = overrides
    }

    // Quoted-printable is nodemailer's default transfer encoding for long-lined HTML; decode it
    // so tests can assert on the actual content (long tracking URLs get soft-wrapped otherwise).
    static decodeQuotedPrintable(data: string): string {
        return data.replace(/=\r\n/g, '').replace(/=([0-9A-F]{2})/g, (_, hex) => String.fromCharCode(parseInt(hex, 16)))
    }

    private handleConnection(socket: net.Socket): void {
        let buffer = ''
        let inData = false
        let current: ReceivedSmtpEmail = { mailFrom: '', rcptTo: [], data: '' }
        let auth: ReceivedSmtpEmail['auth']

        socket.write('220 test.local ESMTP fake\r\n')
        socket.on('error', () => {})
        socket.on('data', (chunk) => {
            buffer += chunk.toString('utf8')
            while (true) {
                if (inData) {
                    const endIndex = buffer.indexOf('\r\n.\r\n')
                    if (endIndex === -1) {
                        return
                    }
                    current.data = buffer.slice(0, endIndex)
                    buffer = buffer.slice(endIndex + 5)
                    inData = false
                    this.received.push({ ...current, auth })
                    current = { mailFrom: '', rcptTo: [], data: '' }
                    socket.write('250 2.0.0 OK: queued\r\n')
                    continue
                }
                const lineEnd = buffer.indexOf('\r\n')
                if (lineEnd === -1) {
                    return
                }
                const line = buffer.slice(0, lineEnd)
                buffer = buffer.slice(lineEnd + 2)
                const command = line.split(' ')[0].toUpperCase()

                if (command === 'EHLO' || command === 'HELO') {
                    socket.write('250-test.local\r\n250-AUTH PLAIN\r\n250 SIZE 10485760\r\n')
                } else if (command === 'AUTH') {
                    const decoded = Buffer.from(line.split(' ')[2], 'base64').toString('utf8')
                    const [, user, pass] = decoded.split('\0')
                    auth = { user, pass }
                    socket.write('235 2.7.0 Authentication successful\r\n')
                } else if (command === 'MAIL') {
                    if (this.respondWith.MAIL) {
                        socket.write(`${this.respondWith.MAIL}\r\n`)
                    } else {
                        current.mailFrom = line.replace(/^MAIL FROM:<(.*)>.*$/i, '$1')
                        socket.write('250 2.1.0 OK\r\n')
                    }
                } else if (command === 'RCPT') {
                    if (this.respondWith.RCPT) {
                        socket.write(`${this.respondWith.RCPT}\r\n`)
                    } else {
                        current.rcptTo.push(line.replace(/^RCPT TO:<(.*)>.*$/i, '$1'))
                        socket.write('250 2.1.5 OK\r\n')
                    }
                } else if (command === 'DATA') {
                    if (this.respondWith.DATA) {
                        socket.write(`${this.respondWith.DATA}\r\n`)
                    } else {
                        inData = true
                        socket.write('354 End data with <CR><LF>.<CR><LF>\r\n')
                    }
                } else if (command === 'QUIT') {
                    socket.write('221 2.0.0 Bye\r\n')
                    socket.end()
                    return
                } else {
                    socket.write('250 2.0.0 OK\r\n')
                }
            }
        })
    }
}
