import { SESv2Client, SendEmailCommand } from '@aws-sdk/client-sesv2'
import childProcess, { spawn } from 'child_process'
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

    it('answers a send with a held fault, stamps when it first answered, and lifts it on release', async () => {
        const held = await edge.hold(REJECT)
        const before = await held.firstAppliedAt()
        const observed = held.observed()
        const sentAt = Date.now()
        const answer = await send()
        const seen = await observed
        const appliedAt = await held.firstAppliedAt()
        await held.release()

        expect({ before, answer, seen, stamped: appliedAt! >= sentAt, after: await send() }).toEqual({
            before: undefined,
            answer: 'MessageRejected',
            seen: true,
            stamped: true,
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

    it('rejects startup when the edge process cannot spawn', async () => {
        const fork = childProcess.fork
        jest.spyOn(childProcess, 'fork').mockImplementationOnce((modulePath, args, options) =>
            fork(modulePath, args!, { ...options, execPath: '/nonexistent/node' })
        )

        await expect(startEdgeProcess({ port: 0 })).rejects.toThrow(
            'the provider edge process failed: spawn /nonexistent/node ENOENT'
        )
    }, 5_000)
})
