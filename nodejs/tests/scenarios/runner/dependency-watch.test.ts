import http from 'http'
import { AddressInfo } from 'net'

import { defaultConfig } from '~/common/config/config'

import { Probes, dependencyProbes, expectOk, failedProbes } from '../environment/stack'
import { ProviderEdge, startProviderEdge } from '../provider-edge'
import { DependencyLoss, dependencyReasonOf, watchDependencies } from './dependency-watch'

const POSTGRES = defaultConfig.DATABASE_URL!
const UNREACHABLE_POSTGRES = 'postgres://posthog:posthog@127.0.0.1:1/posthog'
const VALKEY = { host: '127.0.0.1', port: 6379 }
const RUNNER_BLOCKS_MS = 2100

const busyFor = (ms: number): void => {
    const until = performance.now() + ms
    while (performance.now() < until) {}
}

describe('dependency watch', () => {
    let edge: ProviderEdge

    beforeAll(async () => {
        edge = await startProviderEdge({ port: 0, trackingKeys: 'scenario-tracking-key' })
    })

    afterAll(() => edge.close())

    const edgeAndPostgres = (postgresUrl: string): Probes => {
        const { 'provider-edge': providerEdge, postgres } = dependencyProbes(edge.url, postgresUrl, VALKEY)
        return { 'provider-edge': providerEdge, postgres }
    }

    const watched = async (
        probes: Probes,
        runnerBlocksMs = 0
    ): Promise<{ losses: DependencyLoss[]; reason?: string }> => {
        const startedAt = Date.now()
        const saturating = runnerBlocksMs > 0 ? setInterval(() => busyFor(runnerBlocksMs), 5) : undefined
        try {
            const losses = await watchDependencies(() => failedProbes(probes), 60_000).stop()
            const topStep = { scale: 320, startedAt, endedAt: startedAt + 120_000 }
            return { losses, reason: dependencyReasonOf(losses, [topStep]) }
        } finally {
            clearInterval(saturating)
        }
    }

    it('names a harness limit at the step when the runner is too busy to hear healthy dependencies', async () => {
        const { reason } = await watched(edgeAndPostgres(POSTGRES), RUNNER_BLOCKS_MS)

        expect(reason).toMatch(
            /^the runner's event loop was too busy to check provider-edge, postgres in the 320x step \(busy \d+% of the check\), a harness limit: the run cannot tell whether they stayed up$/
        )
    }, 30_000)

    it('names a dependency that went away while the runner was idle, with its step and error', async () => {
        const { reason } = await watched(edgeAndPostgres(UNREACHABLE_POSTGRES))

        expect(reason).toMatch(
            /^dependencies went away: postgres in the 320x step \(Postgres at 127\.0\.0\.1:1 failed: .*ECONNREFUSED.*\)$/
        )
    })

    it('keeps a dependency that failed once and answered the next probe as evidence, not as a loss', async () => {
        let answered = 0
        const blip = http.createServer((_request, response) => response.writeHead(answered++ === 0 ? 503 : 200).end())
        await new Promise<void>((resolve) => blip.listen(0, '127.0.0.1', resolve))
        try {
            const { port } = blip.address() as AddressInfo

            const { losses, reason } = await watched({ personhog: () => expectOk(`http://127.0.0.1:${port}`) })

            expect({ reason, kinds: losses.map(({ name, kind }) => `${name} ${kind}`) }).toEqual({
                reason: undefined,
                kinds: ['personhog recovered'],
            })
        } finally {
            blip.close()
        }
    })
})
