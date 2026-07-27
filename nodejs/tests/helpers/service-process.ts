import { ChildProcessWithoutNullStreams, spawn } from 'child_process'
import http, { RequestOptions } from 'http'
import net, { AddressInfo } from 'net'

const OUTPUT_BUFFER_LIMIT = 40_000

export interface HttpResponse {
    statusCode: number
    body: string
}

export interface ProcessExit {
    exitCode: number | null
    signal: NodeJS.Signals | null
    output: string
}

export async function getFreePort(): Promise<number> {
    return await new Promise((resolve, reject) => {
        const server = net.createServer()
        server.on('error', reject)
        server.listen(0, '127.0.0.1', () => {
            const address = server.address() as AddressInfo
            server.close(() => resolve(address.port))
        })
    })
}

export class ServiceProcess {
    private readonly child: ChildProcessWithoutNullStreams
    private readonly exited: Promise<ProcessExit>
    private exitResult: ProcessExit | null = null
    private output = ''
    private stopping = false
    private hasExited = false

    constructor(
        private readonly name: string,
        command: string,
        args: string[],
        options: { cwd: string; env: NodeJS.ProcessEnv }
    ) {
        this.child = spawn(command, args, {
            cwd: options.cwd,
            env: options.env,
            detached: process.platform !== 'win32',
            stdio: 'pipe',
        })

        this.child.stdout.on('data', (chunk) => this.capture('stdout', chunk))
        this.child.stderr.on('data', (chunk) => this.capture('stderr', chunk))

        this.exited = new Promise((resolve) => {
            this.child.once('exit', (exitCode, signal) => {
                this.hasExited = true
                this.exitResult = { exitCode, signal, output: this.getOutput() }
                resolve(this.exitResult)
            })
        })
    }

    async waitForHttpOk(url: string, timeoutMs = 120_000): Promise<void> {
        const deadline = Date.now() + timeoutMs

        while (Date.now() < deadline) {
            if (this.hasExited) {
                throw new Error(`${this.name} exited before ${url} became ready:\n${this.getOutput()}`)
            }

            try {
                const response = await request(url, { method: 'GET' })
                if (response.statusCode >= 200 && response.statusCode < 300) {
                    return
                }
            } catch {
                // Retry until the service has bound its HTTP port.
            }

            await delay(250)
        }

        throw new Error(`${this.name} did not become ready at ${url} within ${timeoutMs}ms:\n${this.getOutput()}`)
    }

    async request(url: string, options: RequestOptions & { body?: string }): Promise<HttpResponse> {
        return await request(url, options)
    }

    async waitForExit(timeoutMs = 60_000): Promise<ProcessExit> {
        if (this.exitResult) {
            return { ...this.exitResult, output: this.getOutput() }
        }

        const result = await Promise.race<ProcessExit | null>([this.exited, delay(timeoutMs).then(() => null)])
        if (result === null) {
            throw new Error(`${this.name} did not exit within ${timeoutMs}ms:\n${this.getOutput()}`)
        }

        return { ...result, output: this.getOutput() }
    }

    async stop(): Promise<void> {
        if (this.stopping || this.hasExited) {
            return
        }

        this.stopping = true
        this.kill('SIGTERM')

        const stopped = await Promise.race([this.exited.then(() => true), delay(10_000).then(() => false)])
        if (!stopped) {
            this.kill('SIGKILL')
            await this.exited
        }
    }

    getOutput(): string {
        return this.output
    }

    private capture(stream: 'stdout' | 'stderr', chunk: Buffer): void {
        this.output += `[${this.name}:${stream}] ${chunk.toString()}`
        if (this.output.length > OUTPUT_BUFFER_LIMIT) {
            this.output = this.output.slice(-OUTPUT_BUFFER_LIMIT)
        }
    }

    private kill(signal: NodeJS.Signals): void {
        if (!this.child.pid) {
            return
        }

        try {
            if (process.platform === 'win32') {
                this.child.kill(signal)
            } else {
                process.kill(-this.child.pid, signal)
            }
        } catch (error: unknown) {
            if (!isNodeError(error) || error.code !== 'ESRCH') {
                throw error
            }
        }
    }
}

async function request(url: string, options: RequestOptions & { body?: string }): Promise<HttpResponse> {
    return await new Promise((resolve, reject) => {
        const req = http.request(url, options, (res) => {
            let body = ''
            res.setEncoding('utf8')
            res.on('data', (chunk) => {
                body += chunk
            })
            res.on('end', () => {
                resolve({ statusCode: res.statusCode ?? 0, body })
            })
        })

        req.on('error', reject)
        req.setTimeout(options.timeout ?? 10_000, () => {
            req.destroy(new Error(`Request to ${url} timed out`))
        })
        if (options.body) {
            req.write(options.body)
        }
        req.end()
    })
}

async function delay(ms: number): Promise<void> {
    await new Promise((resolve) => setTimeout(resolve, ms))
}

function isNodeError(error: unknown): error is NodeJS.ErrnoException {
    return error instanceof Error && 'code' in error
}
