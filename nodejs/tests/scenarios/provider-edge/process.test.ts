import { SESv2Client, SendEmailCommand } from '@aws-sdk/client-sesv2'
import { execFile, execFileSync, spawn } from 'child_process'
import { chmodSync, existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'fs'
import net from 'net'
import { tmpdir } from 'os'
import path from 'path'
import { createInterface } from 'readline'
import { setTimeout as sleep } from 'timers/promises'
import { pathToFileURL } from 'url'

import { internalFetch } from '~/common/utils/request'

import { heldAnswerRule, ruleOf } from './faults'
import { FaultHold } from './index'
import { EdgeProcess, startEdgeProcess } from './process'

const ALICE = 'run-1-1@www.example.com'
const REJECT = ruleOf({ name: 'ses.reject', params: { type: 'rejected' }, dose: { share: 1 } })
const TSX = pathToFileURL(require.resolve('tsx')).href
const NODEJS_DIR = path.join(__dirname, '../../..')
const EDGE_PROCESS = JSON.stringify(require.resolve('./process'))
const WITHOUT_LOG_THREAD = { ...process.env, NODE_ENV: 'production', DEBUG: '' }

const runs = (pid: number | undefined): boolean => {
    try {
        return process.kill(pid!, 0)
    } catch {
        return false
    }
}
const blockRunnerFor = (ms: number): void => void Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms)
const blockRunnerUntil = (done: () => boolean, withinMs: number): boolean => {
    const deadline = Date.now() + withinMs
    while (!done() && Date.now() < deadline) {
        blockRunnerFor(10)
    }
    return done()
}
const bytesWrittenBy = (pid: number): number =>
    Number(/^wchar: (\d+)$/m.exec(readFileSync(`/proc/${pid}/io`, 'utf8'))![1])

describe('provider edge process', () => {
    let edge: EdgeProcess
    let ses: SESv2Client

    beforeEach(async () => {
        edge = await startEdgeProcess({ port: 0 })
        ses = new SESv2Client({
            endpoint: edge.url,
            region: 'us-east-1',
            credentials: { accessKeyId: 'edge', secretAccessKey: 'edge' },
            maxAttempts: 1,
        })
    })

    afterEach(async () => {
        ses.destroy()
        await edge.close()
    })

    const send = (): Promise<string> =>
        ses
            .send(
                new SendEmailCommand({
                    FromEmailAddress: 'flows@www.example.com',
                    Destination: { ToAddresses: [ALICE] },
                    Content: { Simple: { Subject: { Data: 'Hello' }, Body: { Text: { Data: 'Hello there' } } } },
                })
            )
            .then(
                () => 'sent',
                (error: Error) => error.name
            )

    it('answers a send with a held fault, observes and accepts that answer, lifts the fault on release, and lists the unit it hit', async () => {
        const held = await edge.hold(REJECT)
        const observing = held.observed()
        const accepting = held.accepted!(AbortSignal.timeout(10_000))
        const answer = await send()
        const seen = await observing
        const accepted = await accepting
        await held.release()

        expect({ answer, seen, accepted, after: await send(), hits: await held.hits?.() }).toEqual({
            answer: 'MessageRejected',
            seen: true,
            accepted: true,
            after: 'sent',
            hits: ['run-1-1'],
        })
    })

    it('lifts every held fault when the faults are cleared', async () => {
        await edge.hold(REJECT)
        await edge.clearFaults()

        expect(await send()).toBe('sent')
    })

    it.each<[string, (held: FaultHold) => Promise<void>]>([
        ['its valve releases', (held) => held.release()],
        ['the edge clears its faults', () => edge.clearFaults()],
    ])('answers a send it holds once %s', async (_path, remove) => {
        const held = await edge.hold(heldAnswerRule())
        const accepting = held.accepted!(AbortSignal.timeout(10_000))
        const answer = send()
        const accepted = await accepting
        const answeredBeforeRemoval = await Promise.race([answer.then(() => true), sleep(200).then(() => false)])

        await remove(held)

        expect({ accepted, answeredBeforeRemoval, answer: await answer }).toEqual({
            accepted: true,
            answeredBeforeRemoval: false,
            answer: 'sent',
        })
    })

    it('rejects a pending call when the edge process dies', async () => {
        process.kill(edge.pid!, 'SIGSTOP')
        const holding = edge.hold(REJECT)
        process.kill(edge.pid!, 'SIGKILL')

        await expect(holding).rejects.toThrow('the provider edge process exited with SIGKILL')
        await expect(edge.close()).resolves.toBeUndefined()
    }, 10_000)

    const withFakeTimers = async (body: () => Promise<void>): Promise<void> => {
        jest.useFakeTimers({ doNotFake: ['nextTick', 'queueMicrotask', 'hrtime', 'performance', 'Date'] })
        try {
            await body()
        } finally {
            jest.useRealTimers()
        }
    }
    const outcomeOf = (answer: Promise<unknown>): Promise<string> =>
        answer.then(
            () => 'answered',
            (error: Error) => error.message
        )

    it('gives up on an edge process that stops answering, and rejects every later call', async () => {
        await edge.close()
        edge = await startEdgeProcess({ port: 0 }, { answersWithinMs: 500 })
        await withFakeTimers(async () => {
            process.kill(edge.pid!, 'SIGSTOP')
            const holding = outcomeOf(edge.hold(REJECT))
            jest.advanceTimersByTime(250)
            const clearing = outcomeOf(edge.clearFaults())
            jest.advanceTimersByTime(250)
            jest.advanceTimersByTime(1)

            expect({
                waiting: await Promise.all([holding, clearing]),
                later: await outcomeOf(edge.clearFaults()),
                edgeRuns: runs(edge.pid),
            }).toEqual({
                waiting: [
                    'the provider edge process did not answer add within 500 ms',
                    'the provider edge process did not answer add within 500 ms',
                ],
                later: 'the provider edge process did not answer add within 500 ms',
                edgeRuns: false,
            })
        })
    }, 10_000)

    it('rejects a call it gave up on when it cannot kill the edge process', async () => {
        await edge.close()
        edge = await startEdgeProcess({ port: 0 }, { answersWithinMs: 500 })
        const signal = process.kill.bind(process)
        const kill = jest.spyOn(process, 'kill').mockImplementation((pid, name) => {
            if (pid < 0) {
                throw Object.assign(new Error('kill EPERM'), { code: 'EPERM' })
            }
            return signal(pid, name)
        })
        try {
            await withFakeTimers(async () => {
                process.kill(edge.pid!, 'SIGSTOP')
                const holding = outcomeOf(edge.hold(REJECT))
                jest.advanceTimersByTime(500)
                jest.advanceTimersByTime(1)

                expect({ outcome: await holding, later: await outcomeOf(edge.clearFaults()) }).toEqual({
                    outcome: 'the provider edge process did not answer add within 500 ms, and could not be killed',
                    later: 'the provider edge process did not answer add within 500 ms, and could not be killed',
                })
            })
        } finally {
            kill.mockRestore()
        }
    }, 10_000)

    // The test knows the edge wrote its reply from the edge's write count in /proc, which only Linux has.
    const itOnLinux = process.platform === 'linux' ? it : it.skip

    itOnLinux(
        'drops a reply that reaches the runner after it gave up on the call',
        async () => {
            await edge.close()
            edge = await startEdgeProcess({ port: 0 }, { answersWithinMs: 500 })
            await withFakeTimers(async () => {
                process.kill(edge.pid!, 'SIGSTOP')
                const holding = outcomeOf(edge.hold(REJECT))
                const writtenBefore = bytesWrittenBy(edge.pid!)
                process.kill(edge.pid!, 'SIGCONT')
                const replyWritten = blockRunnerUntil(() => bytesWrittenBy(edge.pid!) > writtenBefore, 5000)
                jest.advanceTimersByTime(500)
                jest.advanceTimersByTime(1)

                expect({ replyWritten, outcome: await holding, edgeRuns: runs(edge.pid) }).toEqual({
                    replyWritten: true,
                    outcome: 'the provider edge process did not answer add within 500 ms',
                    edgeRuns: false,
                })
            })
        },
        10_000
    )

    it('settles a reply that waits on the channel when the runner was blocked past the deadline', async () => {
        await edge.close()
        edge = await startEdgeProcess({ port: 0 }, { answersWithinMs: 500 })
        process.kill(edge.pid!, 'SIGSTOP')
        const holding = outcomeOf(edge.hold(REJECT))
        setImmediate(() => {
            process.kill(edge.pid!, 'SIGCONT')
            blockRunnerFor(2000)
        })

        expect({ outcome: await holding, edgeRuns: runs(edge.pid) }).toEqual({ outcome: 'answered', edgeRuns: true })
    }, 10_000)

    it('keeps answering after a call it could not send', async () => {
        await withFakeTimers(async () => {
            await expect(edge.hold(Object.assign({}, REJECT, { unsendable: 1n }))).rejects.toThrow('BigInt')
            jest.advanceTimersByTime(30_001)

            await expect(edge.clearFaults()).resolves.toBeUndefined()
        })
    })

    it.each([
        ['and kills the edge', '', '', 'Do not know how to serialize a BigInt'],
        [
            'when it cannot kill the edge',
            `const signal = process.kill.bind(process)
            process.kill = (pid, name) => {
                if (pid < 0) throw Object.assign(new Error('kill EPERM'), { code: 'EPERM' })
                return signal(pid, name)
            }`,
            'process.exit()',
            'kill EPERM',
        ],
    ])(
        'rejects a start whose options it could not send, and leaves nothing to reject later, %s',
        async (_, signalBoundary, afterOutcome, expected) => {
            const runner = `${signalBoundary}
            require(${EDGE_PROCESS})
            .startEdgeProcess(Object.assign({ port: 0 }, { unsendable: 1n }), { startsWithinMs: 300 })
            .then((edge) => edge.close().then(() => 'started'), (error) => error.message)
            .then((outcome) => setTimeout(() => process.stdout.write(outcome, () => { ${afterOutcome} }), 1000))`
            const outcome = await new Promise<string>((resolve) =>
                execFile(
                    process.execPath,
                    ['--import', TSX, '-e', runner],
                    { cwd: NODEJS_DIR, env: WITHOUT_LOG_THREAD, timeout: 20_000 },
                    (error, stdout, stderr) => resolve(error ? `${stdout}, then ${error.message}\n${stderr}` : stdout)
                )
            )

            expect(outcome).toBe(expected)
        },
        30_000
    )

    it('gives up on an edge process that does not start, and kills what it started', async () => {
        const bin = mkdtempSync(path.join(tmpdir(), 'edge-openssl-'))
        const pidFile = path.join(bin, 'openssl.pid')
        writeFileSync(path.join(bin, 'openssl'), '#!/bin/sh\necho $$ > "$EDGE_OPENSSL_PID"\nexec sleep 600\n')
        chmodSync(path.join(bin, 'openssl'), 0o755)
        const runner = `require(${EDGE_PROCESS})
            .startEdgeProcess({ port: 0, caDir: ${JSON.stringify(path.join(bin, 'ca'))} }, { startsWithinMs: 10_000 })
            .then((edge) => edge.close().then(() => 'started'), (error) => error.message)
            .then((outcome) => process.stdout.write(outcome))`
        const opensslPid = (): number | undefined =>
            existsSync(pidFile) ? Number(readFileSync(pidFile, 'utf8')) : undefined
        const opensslRuns = (): boolean => {
            try {
                return !execFileSync('ps', ['-o', 'stat=', '-p', String(opensslPid())], {
                    encoding: 'utf8',
                }).startsWith('Z')
            } catch (error) {
                if ((error as { status?: number }).status === 1) {
                    return false
                }
                throw error
            }
        }
        try {
            const outcome = await new Promise<string>((resolve) =>
                execFile(
                    process.execPath,
                    ['--import', TSX, '-e', runner],
                    {
                        cwd: NODEJS_DIR,
                        env: { ...WITHOUT_LOG_THREAD, PATH: `${bin}:${process.env.PATH}`, EDGE_OPENSSL_PID: pidFile },
                        timeout: 20_000,
                    },
                    (error, stdout, stderr) => resolve(error ? `${stdout}, then ${error.message}\n${stderr}` : stdout)
                )
            )

            expect({ outcome, opensslStarted: opensslPid() !== undefined, opensslRuns: opensslRuns() }).toEqual({
                outcome: 'the provider edge process did not start within 10000 ms',
                opensslStarted: true,
                opensslRuns: false,
            })
        } finally {
            if (opensslRuns()) {
                process.kill(opensslPid()!, 'SIGKILL')
            }
            rmSync(bin, { recursive: true, force: true })
        }
    }, 30_000)

    it('rejects startup on a port another listener holds', async () => {
        await expect(startEdgeProcess({ port: Number(new URL(edge.url).port) })).rejects.toThrow('EADDRINUSE')
    })

    it('frees its port by the time it has closed', async () => {
        const port = Number(new URL(edge.url).port)
        await edge.close()
        const listener = net.createServer()
        const bound = new Promise<string>((resolve) => {
            listener.once('error', (error: NodeJS.ErrnoException) => resolve(error.code ?? error.message))
            listener.listen(port, '127.0.0.1', () => resolve('bound'))
        })
        const outcome = await bound
        listener.close()
        edge = await startEdgeProcess({ port: 0 })

        expect(outcome).toBe('bound')
    })

    it('keeps answering after a Ctrl-C reaches the runner it belongs to', async () => {
        const runner = spawn(
            process.execPath,
            [
                '--import',
                TSX,
                '-e',
                `process.on('SIGINT', () => process.stdout.write('interrupted\\n'))
                require(${EDGE_PROCESS}).startEdgeProcess({ port: 0 }).then((edge) => process.stdout.write(edge.url + '\\n'))`,
            ],
            { cwd: NODEJS_DIR, detached: true, stdio: ['ignore', 'pipe', 'inherit'] }
        )
        try {
            const lines = createInterface({ input: runner.stdout! })[Symbol.asyncIterator]()
            const url = (await lines.next()).value as string
            process.kill(-runner.pid!, 'SIGINT')
            await lines.next()

            expect((await internalFetch(`${url}/_health`)).status).toBe(200)
        } finally {
            process.kill(-runner.pid!, 'SIGKILL')
        }
    }, 30_000)

    it.each([
        [
            'its node binary is missing',
            'process.execPath = "/nonexistent/node"',
            /^the provider edge process failed: spawn \/nonexistent\/node ENOENT$/,
        ],
        [
            'the runner has no file descriptor left',
            'for (;;) { try { held.push(openSync("/dev/null", "r")) } catch { break } }',
            /^the provider edge process failed: spawn \S+ EMFILE$/,
        ],
    ])(
        'rejects startup when the edge process cannot spawn because %s',
        async (_case, exhaust, failure) => {
            const runner = `const { startEdgeProcess } = require(${EDGE_PROCESS})
            const { openSync, closeSync } = require('fs')
            const held = []
            ${exhaust}
            const starting = startEdgeProcess({ port: 0 })
            held.forEach(closeSync)
            starting.then((edge) => edge.close().then(() => 'started'), (error) => error.message).then((outcome) => process.stdout.write(outcome))`
            const outcome = await new Promise<string>((resolve) =>
                execFile(
                    'bash',
                    [
                        '-c',
                        'ulimit -S -n 1024 2>/dev/null; exec "$0" --import "$1" -e "$2"',
                        process.execPath,
                        TSX,
                        runner,
                    ],
                    { cwd: NODEJS_DIR, env: WITHOUT_LOG_THREAD, timeout: 20_000 },
                    (error, stdout, stderr) => resolve(error ? `${stdout}, then ${error.message}\n${stderr}` : stdout)
                )
            )

            expect(outcome).toMatch(failure)
        },
        30_000
    )
})
