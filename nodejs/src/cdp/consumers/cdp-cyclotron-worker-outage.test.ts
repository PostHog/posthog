import { createMockJobQueue } from '~/tests/helpers/mocks/job-queue.mock'

import { createServer as createHttpServer } from 'http'
import { AddressInfo, Socket, connect, createServer as createTcpServer } from 'net'

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

const startPostgresProxy = async (databaseUrl: string): Promise<{ url: string; cut: () => Promise<void> }> => {
    const upstream = new URL(databaseUrl)
    const sockets = new Set<Socket>()
    const server = createTcpServer((client) => {
        const target = connect(Number(upstream.port || 5432), upstream.hostname)
        client.pipe(target).pipe(client)
        for (const socket of [client, target]) {
            sockets.add(socket)
            socket.on('error', () => {})
            socket.on('close', () => sockets.delete(socket))
        }
    })
    await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
    const proxied = new URL(databaseUrl)
    proxied.hostname = '127.0.0.1'
    proxied.port = String((server.address() as AddressInfo).port)
    return {
        url: proxied.toString(),
        cut: () =>
            new Promise<void>((resolve) => {
                server.close(() => resolve())
                sockets.forEach((socket) => socket.destroy())
            }),
    }
}

describe('CdpCyclotronWorker during a Postgres outage', () => {
    let hub: Hub
    let team: Team
    let receiver: Awaited<ReturnType<typeof startWebhookReceiver>>

    beforeEach(async () => {
        hub = await createHub()
        team = (await createTestTeamFixture(hub.postgres)).team
        receiver = await startWebhookReceiver()
    })

    afterEach(async () => {
        receiver.close()
        await closeHub(hub)
    })

    it.each([
        ['every team', 'while it builds the inputs', false],
        ['every team', 'when it fetches with built inputs', true],
        ['only the team of a sibling destination', 'while it builds the inputs', false],
    ])(
        'sends nothing when %s preloads and the integration lookup fails %s',
        async (allowlisted, _, inputsBuilt) => {
            const webhookUrl = `${receiver.url}/webhook-with-integration`
            const fn = await insertHogFunction(
                hub.postgres,
                team.id,
                createHogFunction({
                    ...HOG_EXAMPLES.simple_fetch,
                    ...HOG_INPUTS_EXAMPLES.simple_fetch,
                    ...HOG_FILTERS_EXAMPLES.pageview_or_autocapture_filter,
                })
            )
            const otherTeam = (await createTestTeamFixture(hub.postgres)).team
            const integration = await insertIntegration(hub.postgres, otherTeam.id, { kind: 'oauth' })
            const fnWithIntegration = await insertHogFunction(
                hub.postgres,
                otherTeam.id,
                createHogFunction({
                    ...HOG_EXAMPLES.simple_fetch,
                    inputs_schema: [
                        ...HOG_INPUTS_EXAMPLES.simple_fetch.inputs_schema!,
                        { key: 'oauth', type: 'integration', label: 'OAuth', integration: 'oauth' },
                    ],
                    inputs: {
                        ...HOG_INPUTS_EXAMPLES.simple_fetch.inputs,
                        url: { value: webhookUrl, bytecode: ['_h', 32, webhookUrl] },
                        oauth: { value: integration.id },
                    },
                    ...HOG_FILTERS_EXAMPLES.pageview_or_autocapture_filter,
                })
            )

            const postgres = await startPostgresProxy(hub.DATABASE_URL)
            const outageHub = await createHub({
                DATABASE_URL: postgres.url,
                CDP_CYCLOTRON_PRELOAD_INTEGRATIONS_TEAMS: allowlisted === 'every team' ? '*' : String(team.id),
            })
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
                        inputs: inputsBuilt ? { url: webhookUrl } : undefined,
                    }),
                ]

                await expect(worker.processInvocations(batch)).rejects.toThrow(DependencyUnavailableError)
                expect(receiver.received).toEqual([])
            } finally {
                await postgres.cut()
                await closeHub(outageHub)
            }
        },
        30_000
    )
})
