import { createMockJobQueue } from '~/tests/helpers/mocks/job-queue.mock'
import { mockFetch } from '~/tests/helpers/mocks/request.mock'

import { existsSync, readFileSync, readdirSync, writeFileSync } from 'fs'
import { isEqual } from 'lodash'
import { DateTime } from 'luxon'
import path from 'path'
import { Pool } from 'pg'

import { HogFlow } from '~/cdp/schema/hogflow'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { parseJSON } from '~/common/utils/json-parse'
import { createCdpConsumerDeps } from '~/tests/helpers/cdp'
import { assertTestDatabaseName } from '~/tests/helpers/database-guard'
import { waitForExpect } from '~/tests/helpers/expectations'
import { getFirstTeam, resetTestDatabase } from '~/tests/helpers/sql'

import { Hub, Team } from '../types'
import { FixtureHogFlowBuilder } from './_tests/builders/hogflow.builder'
import { HOG_FILTERS_EXAMPLES } from './_tests/examples'
import { createHogExecutionGlobals, insertHogFunctionTemplate } from './_tests/fixtures'
import { insertHogFlow } from './_tests/fixtures-hogflows'
import { CdpCyclotronWorkerHogFlow } from './consumers/cdp-cyclotron-worker-hogflow.consumer'
import { CdpEventsConsumer } from './consumers/cdp-events.consumer'
import { CyclotronV2Manager } from './services/cyclotron-v2'
import { CyclotronJobQueuePostgresV2 } from './services/job-queue/job-queue-postgres-v2'

const CYCLOTRON_NODE_DB_URL =
    process.env.CYCLOTRON_NODE_DATABASE_URL ?? 'postgres://posthog:posthog@localhost:5432/test_cyclotron_node'
const CORPUS_DIR = path.join(__dirname, '_tests', 'stored-job-state')
const RECORD_NEW_SHAPES = process.env.UPDATE_STORED_SHAPES === '1'
const RUN_TIME_MS = '$RUN_TIME_MS'
const RUN_TIME_ISO = '$RUN_TIME_ISO'
const FETCH_TEMPLATE_ID = 'template-stored-job-state-fetch'
const EVENT_UUID = 'b3a1fe86-b10c-43cc-acaf-d208977608d0'

type CorpusEntry = { scenario: string; about: string; stored: unknown }
type Workflow = Parameters<FixtureHogFlowBuilder['withWorkflow']>[0]
type ParkingStep = Workflow['actions'][string]

const SCENARIOS: Record<string, ParkingStep | null> = {
    triggered: null,
    'parked-on-delay': { type: 'delay', config: { delay_duration: '1h' } },
    'parked-on-wait': {
        type: 'wait_until_condition',
        config: { condition: { filters: HOG_FILTERS_EXAMPLES.elements_text_filter.filters }, max_wait_duration: '1h' },
    },
}

const fetchedUrl = (scenario: string): string => `https://example.com/stored-job-state/${scenario}`

function workflowFor(scenario: string): Workflow {
    const parking = SCENARIOS[scenario]
    const firstStep = parking ? 'park' : 'fetch'
    return {
        actions: {
            trigger: {
                type: 'trigger',
                config: { type: 'event', filters: HOG_FILTERS_EXAMPLES.no_filters.filters ?? {} },
            },
            ...(parking ? { park: { ...parking, on_error: 'abort' } } : {}),
            fetch: {
                type: 'function',
                on_error: 'abort',
                config: {
                    template_id: FETCH_TEMPLATE_ID,
                    inputs: { url: { value: fetchedUrl(scenario) }, method: { value: 'POST' } },
                },
            },
            exit: { type: 'exit', config: {} },
        },
        edges: [
            { from: 'trigger', to: firstStep, type: 'continue' },
            ...(parking ? [{ from: 'park', to: 'fetch', type: 'continue' as const }] : []),
            { from: 'fetch', to: 'exit', type: 'continue' },
        ],
    }
}

function readEntry(file: string): CorpusEntry {
    return parseJSON(readFileSync(path.join(CORPUS_DIR, file), 'utf-8'))
}

function readCorpus(): { file: string; entry: CorpusEntry }[] {
    return readdirSync(CORPUS_DIR)
        .filter((file) => file.endsWith('.json'))
        .sort()
        .map((file) => ({ file, entry: readEntry(file) }))
}

function isWithin(ms: number, window: { from: number; to: number }): boolean {
    return ms >= window.from && ms <= window.to
}

function withRunTimesAsTokens(value: unknown, window: { from: number; to: number }): unknown {
    if (typeof value === 'number') {
        return isWithin(value, window) ? RUN_TIME_MS : value
    }
    if (typeof value === 'string') {
        const parsed = DateTime.fromISO(value)
        return parsed.isValid && value.length >= 20 && isWithin(parsed.toMillis(), window) ? RUN_TIME_ISO : value
    }
    if (Array.isArray(value)) {
        return value.map((item) => withRunTimesAsTokens(item, window))
    }
    if (value && typeof value === 'object') {
        return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, withRunTimesAsTokens(v, window)]))
    }
    return value
}

function withTokensAsTime(value: unknown, runAt: DateTime): unknown {
    if (value === RUN_TIME_MS) {
        return runAt.toMillis()
    }
    if (value === RUN_TIME_ISO) {
        return runAt.toISO()
    }
    if (Array.isArray(value)) {
        return value.map((item) => withTokensAsTime(item, runAt))
    }
    if (value && typeof value === 'object') {
        return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, withTokensAsTime(v, runAt)]))
    }
    return value
}

function recordShapeIfChanged(scenario: string, stored: unknown): void {
    const current = path.join(CORPUS_DIR, `${scenario}.json`)
    const previous = existsSync(current) ? readEntry(`${scenario}.json`) : undefined
    if (isEqual(previous?.stored, stored)) {
        return
    }
    if (previous) {
        const today = DateTime.utc().toISODate()
        let archived = path.join(CORPUS_DIR, `${scenario}.${today}.json`)
        for (let n = 2; existsSync(archived); n++) {
            archived = path.join(CORPUS_DIR, `${scenario}.${today}-${n}.json`)
        }
        const about = `The shape master wrote for this scenario until ${today}.`
        writeFileSync(archived, JSON.stringify({ ...previous, about }, null, 4) + '\n')
    }
    const about = 'The shape the current code writes for this scenario.'
    writeFileSync(current, JSON.stringify({ scenario, about, stored }, null, 4) + '\n')
}

describe('Stored Cyclotron job state', () => {
    jest.setTimeout(30000)

    let hub: Hub
    let team: Team
    let cyclotronPool: Pool
    let manager: CyclotronV2Manager
    let hogflowQueue: CyclotronJobQueuePostgresV2
    let worker: CdpCyclotronWorkerHogFlow | undefined
    let deps: ReturnType<typeof createCdpConsumerDeps>

    beforeAll(async () => {
        cyclotronPool = new Pool({ connectionString: CYCLOTRON_NODE_DB_URL })
        const { rows } = await cyclotronPool.query('SELECT current_database() AS name')
        assertTestDatabaseName(rows[0].name, 'Cyclotron node Postgres')
        manager = new CyclotronV2Manager({ pool: { dbUrl: CYCLOTRON_NODE_DB_URL, maxConnections: 2 } })
    })

    afterAll(async () => {
        await manager.disconnect()
        await cyclotronPool.end()
    })

    beforeEach(async () => {
        await resetTestDatabase()
        await cyclotronPool.query('DELETE FROM cyclotron_jobs')
        hub = await createHub()
        hub.CDP_CYCLOTRON_BATCH_DELAY_MS = 50
        team = await getFirstTeam(hub.postgres)
        await insertHogFunctionTemplate(hub.postgres, {
            id: FETCH_TEMPLATE_ID,
            name: 'Stored job state fetch',
            code: `let res := fetch(f'{inputs.url}/{event.uuid}', {'method': inputs.method});`,
            inputs_schema: [
                { key: 'url', type: 'string', required: true },
                { key: 'method', type: 'string', required: false },
            ],
        })
        deps = createCdpConsumerDeps(hub)
        hogflowQueue = new CyclotronJobQueuePostgresV2(hub.CONSUMER_BATCH_SIZE, hub)
        await hogflowQueue.startAsProducer()
        mockFetch.mockClear()
        worker = undefined
    })

    afterEach(async () => {
        await worker?.stop()
        await hogflowQueue.stopProducer()
        await closeHub(hub)
    })

    async function createScenarioWorkflow(scenario: string): Promise<HogFlow> {
        const flow = new FixtureHogFlowBuilder()
            .withTeamId(team.id)
            .withStatus('active')
            .withWorkflow(workflowFor(scenario))
            .build()
        await insertHogFlow(hub.postgres, flow)
        return flow
    }

    async function startWorker(): Promise<void> {
        worker = new CdpCyclotronWorkerHogFlow(hub, deps, hogflowQueue)
        await worker.start()
    }

    async function storedState(): Promise<Buffer> {
        const { rows } = await cyclotronPool.query(`SELECT state FROM cyclotron_jobs`)
        expect(rows).toHaveLength(1)
        return rows[0].state
    }

    async function writeScenario(scenario: string): Promise<Buffer> {
        await createScenarioWorkflow(scenario)
        const events = new CdpEventsConsumer(hub, deps, { hogQueue: createMockJobQueue(), hogflowQueue })
        const globals = createHogExecutionGlobals({
            project: { id: team.id, name: 'test', url: 'http://localhost:8000/projects/1' },
            event: {
                uuid: EVENT_UUID,
                event: '$pageview',
                elements_chain: '',
                distinct_id: 'stored-job-state-distinct-id',
                url: 'http://localhost:8000/events/1',
                properties: { $current_url: 'https://example.com' },
                timestamp: '2024-09-03T09:00:00Z',
            },
        })
        await (
            await events.processBatch([globals])
        ).backgroundTask
        if (!SCENARIOS[scenario]) {
            return storedState()
        }
        await startWorker()
        await waitForExpect(async () => {
            const { rows } = await cyclotronPool.query(
                `SELECT 1 FROM cyclotron_jobs WHERE status = 'available' AND scheduled > NOW()`
            )
            expect(rows).toHaveLength(1)
        }, 10000)
        return storedState()
    }

    async function jobStatuses(): Promise<string[]> {
        const { rows } = await cyclotronPool.query(`SELECT status FROM cyclotron_jobs`)
        return rows.map((row) => row.status)
    }

    describe.each(Object.keys(SCENARIOS))('%s', (scenarioName) => {
        it('stores the shape its corpus entry records (UPDATE_STORED_SHAPES=1 keeps the old one as history)', async () => {
            const startedAt = Date.now()
            const state = await writeScenario(scenarioName)
            const window = { from: startedAt - 60_000, to: Date.now() + 2 * 24 * 3600_000 }
            const stored = withRunTimesAsTokens(parseJSON(state.toString('utf-8')), window)

            if (RECORD_NEW_SHAPES) {
                recordShapeIfChanged(scenarioName, stored)
            }

            expect(stored).toEqual(readEntry(`${scenarioName}.json`).stored)
        })
    })

    describe.each(readCorpus())('$file', ({ entry }) => {
        it('resumes on the current code and runs the rest of the workflow', async () => {
            const flow = await createScenarioWorkflow(entry.scenario)
            const stored = withTokensAsTime(entry.stored, DateTime.utc().minus({ hours: 2 }))
            await manager.createJob({
                teamId: team.id,
                functionId: flow.id,
                queueName: 'hogflow',
                scheduled: new Date(),
                state: Buffer.from(JSON.stringify(stored)),
            })

            await startWorker()

            await waitForExpect(() => {
                expect(mockFetch).toHaveBeenCalledWith(
                    `${fetchedUrl(entry.scenario)}/${EVENT_UUID}`,
                    expect.objectContaining({ method: 'POST' })
                )
            }, 10000)
            await waitForExpect(async () => expect(await jobStatuses()).toEqual(['completed']), 10000)
        })
    })
})
