import { createMockJobQueue } from '~/tests/helpers/mocks/job-queue.mock'

import { createServer as createHttpServer } from 'http'
import { AddressInfo, Server, Socket, connect, createServer as createTcpServer } from 'net'

import { DependencyUnavailableError } from '~/common/utils/db/error'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { createCdpConsumerDeps } from '~/tests/helpers/cdp'
import { createTestTeamFixture } from '~/tests/helpers/sql'

import { Hub, Team } from '../../types'
import { HOG_EXAMPLES, HOG_FILTERS_EXAMPLES, HOG_INPUTS_EXAMPLES } from '../_tests/examples'
import {
    createExampleInvocation,
    createHogExecutionGlobals,
    createHogFunction,
    insertHogFunction,
    insertIntegration,
} from '../_tests/fixtures'
import { CyclotronJobInvocationHogFunction, HogFunctionType } from '../types'
import { CdpCyclotronWorker } from './cdp-cyclotron-worker.consumer'

const startWebhookReceiver = async (): Promise<{ url: string; received: string[]; close: () => void }> => {
    const received: string[] = []
    const server = createHttpServer((req, res) => {
        received.push(req.url ?? '')
        res.writeHead(200, { 'Content-Type': 'application/json' })
        res.end('{}')
    })
    await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
    return {
        url: `http://127.0.0.1:${(server.address() as AddressInfo).port}`,
        received,
        close: () => server.close(),
    }
}

const startPostgresProxy = async (
    databaseUrl: string
): Promise<{ url: string; cut: () => Promise<void>; restore: () => Promise<void> }> => {
    const upstream = new URL(databaseUrl)
    const sockets = new Set<Socket>()
    let server: Server | null = null
    const listen = async (port: number): Promise<number> => {
        server = createTcpServer((client) => {
            const target = connect(Number(upstream.port || 5432), upstream.hostname)
            client.pipe(target).pipe(client)
            for (const socket of [client, target]) {
                sockets.add(socket)
                socket.on('error', () => {})
                socket.on('close', () => sockets.delete(socket))
            }
        })
        await new Promise<void>((resolve) => server!.listen(port, '127.0.0.1', resolve))
        return (server.address() as AddressInfo).port
    }
    const port = await listen(0)
    const proxied = new URL(databaseUrl)
    proxied.hostname = '127.0.0.1'
    proxied.port = String(port)
    return {
        url: proxied.toString(),
        cut: () =>
            new Promise<void>((resolve) => {
                const closing = server
                server = null
                sockets.forEach((socket) => socket.destroy())
                if (closing) {
                    closing.close(() => resolve())
                } else {
                    resolve()
                }
            }),
        restore: async () => {
            await listen(port)
        },
    }
}

describe('CdpCyclotronWorker when Postgres fails during a fetch that needs an integration', () => {
    let hub: Hub
    let team: Team
    let receiver: Awaited<ReturnType<typeof startWebhookReceiver>>
    let fn: HogFunctionType
    let fnWithIntegration: HogFunctionType

    beforeEach(async () => {
        hub = await createHub()
        team = (await createTestTeamFixture(hub.postgres)).team
        receiver = await startWebhookReceiver()
        fn = await insertHogFunction(
            hub.postgres,
            team.id,
            createHogFunction({
                ...HOG_EXAMPLES.simple_fetch,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                ...HOG_FILTERS_EXAMPLES.pageview_or_autocapture_filter,
            })
        )
        const integration = await insertIntegration(hub.postgres, team.id, { kind: 'oauth' })
        fnWithIntegration = await insertHogFunction(
            hub.postgres,
            team.id,
            createHogFunction({
                ...HOG_EXAMPLES.simple_fetch,
                inputs_schema: [
                    ...HOG_INPUTS_EXAMPLES.simple_fetch.inputs_schema!,
                    { key: 'oauth', type: 'integration', label: 'OAuth', integration: 'oauth' },
                ],
                inputs: { ...HOG_INPUTS_EXAMPLES.simple_fetch.inputs, oauth: { value: integration.id } },
                ...HOG_FILTERS_EXAMPLES.pageview_or_autocapture_filter,
            })
        )
    })

    afterEach(async () => {
        receiver.close()
        await closeHub(hub)
    })

    const runDuringOutage = async (
        config: Partial<Hub>,
        run: (
            worker: CdpCyclotronWorker,
            batch: CyclotronJobInvocationHogFunction[],
            postgres: Awaited<ReturnType<typeof startPostgresProxy>>
        ) => Promise<void>
    ): Promise<void> => {
        const postgres = await startPostgresProxy(hub.DATABASE_URL)
        const outageHub = await createHub({ DATABASE_URL: postgres.url, ...config })
        try {
            const worker = new CdpCyclotronWorker(outageHub, createCdpConsumerDeps(outageHub), createMockJobQueue())
            await worker.hogFunctionManager.getHogFunctions([fn.id, fnWithIntegration.id])
            await postgres.cut()
            const batch = [
                createExampleInvocation(fn, {
                    ...createHogExecutionGlobals(),
                    inputs: { url: `${receiver.url}/webhook-without-integration` },
                }),
                createExampleInvocation(fnWithIntegration, {
                    ...createHogExecutionGlobals(),
                    inputs: { url: `${receiver.url}/webhook-with-integration` },
                }),
            ]
            await run(worker, batch, postgres)
        } finally {
            await postgres.cut()
            await closeHub(outageHub)
        }
    }

    it('reschedules only the invocation whose lookup failed, and it sends once Postgres is back', async () => {
        await runDuringOutage(
            { CDP_FETCH_RETRY_INTEGRATION_LOOKUP_TEAMS: String(team.id) },
            async (worker, batch, postgres) => {
                const [sibling, rescheduled] = await worker.processInvocations(batch)
                expect(sibling.error).toBeUndefined()
                expect(rescheduled.error).toBeUndefined()
                expect(rescheduled.invocation.queueScheduledAt).toBeDefined()
                expect(receiver.received).toEqual(['/webhook-without-integration'])

                await postgres.restore()
                await worker.processInvocations([rescheduled.invocation])
                expect(receiver.received).toEqual(['/webhook-without-integration', '/webhook-with-integration'])
            }
        )
    }, 30_000)

    it('fails the invocation without sending once the lookup used its last attempt', async () => {
        await runDuringOutage(
            { CDP_FETCH_RETRY_INTEGRATION_LOOKUP_TEAMS: '*', CDP_FETCH_RETRIES: 1 },
            async (worker, batch) => {
                const [, gaveUp] = await worker.processInvocations(batch)
                expect(gaveUp.finished).toBe(true)
                expect(gaveUp.error?.message).toBe(
                    'Could not load the integration after 1 attempt, so the request was not sent.'
                )
                expect(receiver.received).toEqual(['/webhook-without-integration'])
            }
        )
    }, 30_000)

    it('fails the whole batch when the team is not allowlisted', async () => {
        await runDuringOutage({ CDP_FETCH_RETRY_INTEGRATION_LOOKUP_TEAMS: '' }, async (worker, batch) => {
            await expect(worker.processInvocations(batch)).rejects.toThrow(DependencyUnavailableError)
        })
    }, 30_000)
})
