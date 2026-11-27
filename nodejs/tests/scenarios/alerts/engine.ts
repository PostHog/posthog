import { execFile } from 'child_process'
import { randomUUID } from 'crypto'
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'fs'
import { AddressInfo, createServer } from 'net'
import os from 'os'
import path from 'path'
import { setTimeout as sleep } from 'timers/promises'
import { promisify } from 'util'
import { parse, stringify } from 'yaml'
import { z } from 'zod'

import { internalFetch } from '~/common/utils/request'

import { VICTORIA_METRICS_IMAGE, VMALERT_IMAGE } from './images'

const READY_WITHIN_MS = 90_000
const DOCKER_RUN_MS = 300_000
const READY_EVERY_MS = 250
const REQUEST_TIMEOUT_MS = 5000

const run = promisify(execFile)

const LabelMap = z
    .object({
        labels: z.record(z.string(), z.string()).default({}),
        roles: z.record(z.string(), z.record(z.string(), z.string())).default({}),
    })
    .strict()

const Scraped = z.object({
    data: z.object({ result: z.array(z.object({ value: z.tuple([z.number(), z.string()]) })) }),
})

export type ScrapeTarget = { role: string; replica: number; metricsUrl: string }

export type Engine = {
    metrics(route: string, params: Record<string, string>): Promise<unknown>
    alerting(route: string, params: Record<string, string>): Promise<unknown>
    stop(): Promise<void>
}

async function freePort(): Promise<number> {
    const server = createServer()
    await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
    const { port } = server.address() as AddressInfo
    await new Promise((resolve) => server.close(resolve))
    return port
}

function scrapeConfigOf(targets: ScrapeTarget[], labelsFile: string, intervalMs: number): string {
    const map = LabelMap.parse(parse(readFileSync(labelsFile, 'utf8')))
    const fill = (labels: Record<string, string>, replica: number): Record<string, string> =>
        Object.fromEntries(
            Object.entries(labels).map(([name, value]) => [name, value.replaceAll('{replica}', `${replica}`)])
        )
    return stringify({
        global: { scrape_interval: `${intervalMs}ms` },
        scrape_configs: [
            {
                job_name: 'scenario',
                static_configs: targets.map(({ role, replica, metricsUrl }) => {
                    const url = new URL(metricsUrl)
                    return {
                        targets: [url.host],
                        labels: {
                            ...map.labels,
                            ...fill(map.roles[role] ?? {}, replica),
                            role,
                            replica: `${replica}`,
                            __metrics_path__: url.pathname,
                            ...Object.fromEntries(
                                [...url.searchParams].map(([name, value]) => [`__param_${name}`, value])
                            ),
                        },
                    }
                }),
            },
        ],
    })
}

async function getJson(url: string): Promise<unknown> {
    const response = await internalFetch(url, { timeoutMs: REQUEST_TIMEOUT_MS })
    if (response.status !== 200) {
        throw new Error(`${url} answered ${response.status}: ${await response.text()}`)
    }
    return response.json()
}

async function until<T>(read: () => Promise<T | undefined>, what: string): Promise<T> {
    const deadline = Date.now() + READY_WITHIN_MS
    for (;;) {
        const value = await read().catch(() => undefined)
        if (value !== undefined) {
            return value
        }
        if (Date.now() > deadline) {
            throw new Error(`${what} within ${READY_WITHIN_MS} ms`)
        }
        await sleep(READY_EVERY_MS)
    }
}

export async function startEngine(
    rules: string,
    labelsFile: string,
    targets: ScrapeTarget[],
    scrapeIntervalMs: number
): Promise<Engine> {
    const scrapeConfig = scrapeConfigOf(targets, labelsFile, scrapeIntervalMs)
    const dir = mkdtempSync(path.join(os.tmpdir(), 'scenario-alerts-'))
    writeFileSync(path.join(dir, 'rules.yaml'), rules)
    writeFileSync(path.join(dir, 'scrape.yaml'), scrapeConfig)
    const [metricsPort, alertPort] = [await freePort(), await freePort()]
    const names = ['metrics', 'vmalert'].map((name) => `scenario-alerts-${name}-${randomUUID()}`)
    const metricsUrl = `http://127.0.0.1:${metricsPort}`
    const alertUrl = `http://127.0.0.1:${alertPort}`
    const container = (name: string, image: string, args: string[]): Promise<unknown> =>
        run(
            'docker',
            ['run', '-d', '--rm', '--name', name, '--network', 'host', '-v', `${dir}:/alerts:ro`, image, ...args],
            { timeout: DOCKER_RUN_MS }
        )
    const stop = async (): Promise<void> => {
        await run('docker', ['rm', '-f', ...names], { timeout: DOCKER_RUN_MS }).catch(() => undefined)
        rmSync(dir, { recursive: true, force: true })
    }
    try {
        await container(names[0], VICTORIA_METRICS_IMAGE, [
            `-httpListenAddr=127.0.0.1:${metricsPort}`,
            '-promscrape.config=/alerts/scrape.yaml',
            '-search.latencyOffset=0s',
            '-inmemoryDataFlushInterval=1s',
        ])
        await until(async () => {
            const { data } = Scraped.parse(
                await getJson(`${metricsUrl}/api/v1/query?query=${encodeURIComponent('count(up)')}`)
            )
            return Number(data.result[0]?.value[1]) === targets.length ? true : undefined
        }, 'the metrics store did not scrape every role')
        await container(names[1], VMALERT_IMAGE, [
            `-httpListenAddr=127.0.0.1:${alertPort}`,
            '-rule=/alerts/rules.yaml',
            `-datasource.url=${metricsUrl}`,
            `-remoteWrite.url=${metricsUrl}`,
            '-notifier.blackhole',
            '-rule.evalDelay=0s',
        ])
        await until(() => getJson(`${alertUrl}/api/v1/rules?type=alert`), 'vmalert did not answer')
    } catch (error) {
        await stop()
        throw error
    }
    return {
        metrics: (route, params) => getJson(`${metricsUrl}${route}?${new URLSearchParams(params).toString()}`),
        alerting: (route, params) => getJson(`${alertUrl}${route}?${new URLSearchParams(params).toString()}`),
        stop,
    }
}
