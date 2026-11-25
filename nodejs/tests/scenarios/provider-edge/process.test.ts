import { SESv2Client, SendEmailCommand } from '@aws-sdk/client-sesv2'
import { execFile, spawn } from 'child_process'
import net from 'net'
import path from 'path'
import { createInterface } from 'readline'
import { pathToFileURL } from 'url'

import { internalFetch } from '~/common/utils/request'

import { ruleOf } from './faults'
import { EdgeProcess, startEdgeProcess } from './process'

const ALICE = 'run-1-1@www.example.com'
const REJECT = ruleOf({ name: 'ses.reject', params: { type: 'rejected' }, dose: { share: 1 } })
const TSX = pathToFileURL(require.resolve('tsx')).href
const NODEJS_DIR = path.join(__dirname, '../../..')
const EDGE_PROCESS = JSON.stringify(require.resolve('./process'))
const WITHOUT_LOG_THREAD = { ...process.env, NODE_ENV: 'production', DEBUG: '' }

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

    it('answers a send with a held fault, observes that answer, and lifts the fault on release', async () => {
        const held = await edge.hold(REJECT)
        const unsent = await held.observed(AbortSignal.abort())
        const observing = held.observed()
        const answer = await send()
        const seen = await observing
        await held.release()

        expect({ unsent, answer, seen, after: await send() }).toEqual({
            unsent: false,
            answer: 'MessageRejected',
            seen: true,
            after: 'sent',
        })
    })

    it('lifts every held fault when the faults are cleared', async () => {
        await edge.hold(REJECT)
        await edge.clearFaults()

        expect(await send()).toBe('sent')
    })

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
                    ['-c', 'ulimit -n 1024 && exec "$0" --import "$1" -e "$2"', process.execPath, TSX, runner],
                    { cwd: NODEJS_DIR, env: WITHOUT_LOG_THREAD, timeout: 20_000 },
                    (error, stdout, stderr) => resolve(error ? `${stdout}, then ${error.message}\n${stderr}` : stdout)
                )
            )

            expect(outcome).toMatch(failure)
        },
        30_000
    )
})
