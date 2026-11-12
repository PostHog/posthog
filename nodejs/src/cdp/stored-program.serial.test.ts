import { mockFetch } from '~/tests/helpers/mocks/request.mock'

import { readFileSync, readdirSync } from 'fs'
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
import { createHogExecutionGlobals, insertHogFunction, insertHogFunctionTemplate } from './_tests/fixtures'
import { insertHogFlow } from './_tests/fixtures-hogflows'
import { CdpCyclotronWorkerHogFlow } from './consumers/cdp-cyclotron-worker-hogflow.consumer'
import { CdpCyclotronWorker } from './consumers/cdp-cyclotron-worker.consumer'
import { CdpEventsConsumer } from './consumers/cdp-events.consumer'
import { CyclotronJobQueuePostgresV2 } from './services/job-queue/job-queue-postgres-v2'
import { HogFunctionTemplateCompiled } from './types'

const CYCLOTRON_NODE_DB_URL =
    process.env.CYCLOTRON_NODE_DATABASE_URL ?? 'postgres://posthog:posthog@localhost:5432/test_cyclotron_node'
const CORPUS_DIR = path.join(__dirname, '_tests', 'stored-program')

type StoredRow = Record<string, unknown>
type CorpusEntry = { scenario: Scenario; about: string; stored: Record<string, StoredRow> }
type Scenario = keyof typeof SCENARIOS
type DeliveredRequest = { url: string; method: string; headers: Record<string, string>; body?: unknown }

const EVENT_PROPERTIES = { email: 'stored-program@example.com', first_name: 'Ada', plan: 'scale' }

const SCENARIOS = {
    destination: {
        table: 'posthog_hogfunction',
        delivers: {
            url: 'https://example.com/stored-program/contacts',
            method: 'PUT',
            headers: { Authorization: 'Bearer stored-program-fake-api-key', 'Content-Type': 'application/json' },
            body: { contacts: [EVENT_PROPERTIES] },
        },
    },
    workflow: {
        table: 'posthog_hogflow',
        delivers: {
            url: 'https://example.com/stored-program/workflow',
            method: 'POST',
            headers: { Authorization: 'Bearer stored-program-fake-workflow-key' },
        },
    },
} satisfies Record<string, { table: string; delivers: DeliveredRequest }>

const WORKFLOW_TEMPLATE: Partial<HogFunctionTemplateCompiled> = {
    id: 'template-stored-program-fetch',
    name: 'Stored program fetch',
    code: `let res := fetch(inputs.url, {'method': 'POST', 'headers': {'Authorization': f'Bearer {inputs.api_key}'}});`,
    inputs_schema: [
        { key: 'url', type: 'string', label: 'URL', secret: false, required: true },
        { key: 'api_key', type: 'string', label: 'API key', secret: true, required: true },
    ],
}

function readCorpus(): { file: string; entry: CorpusEntry }[] {
    return readdirSync(CORPUS_DIR)
        .filter((file) => file.endsWith('.json'))
        .sort()
        .map((file) => ({ file, entry: parseJSON(readFileSync(path.join(CORPUS_DIR, file), 'utf-8')) }))
}

function asColumns(row: StoredRow): StoredRow {
    return Object.fromEntries(
        Object.entries(row).map(([column, value]) => [
            column,
            value !== null && typeof value === 'object' ? JSON.stringify(value) : value,
        ])
    )
}

function deliveredRequests(): DeliveredRequest[] {
    return mockFetch.mock.calls.map(([url, options]) => ({
        url,
        method: options.method,
        headers: options.headers,
        ...(options.body === undefined ? {} : { body: parseJSON(options.body) }),
    }))
}

describe('Stored CDP programs', () => {
    jest.setTimeout(30000)

    let hub: Hub
    let team: Team
    let cyclotronPool: Pool
    let queue: CyclotronJobQueuePostgresV2
    let worker: CdpCyclotronWorker | CdpCyclotronWorkerHogFlow | undefined
    let deps: ReturnType<typeof createCdpConsumerDeps>

    beforeAll(async () => {
        cyclotronPool = new Pool({ connectionString: CYCLOTRON_NODE_DB_URL })
        const { rows } = await cyclotronPool.query('SELECT current_database() AS name')
        assertTestDatabaseName(rows[0].name, 'Cyclotron node Postgres')
    })

    afterAll(async () => {
        await cyclotronPool.end()
    })

    beforeEach(async () => {
        await resetTestDatabase()
        await cyclotronPool.query('DELETE FROM cyclotron_jobs')
        hub = await createHub()
        hub.CDP_CYCLOTRON_BATCH_DELAY_MS = 50
        team = await getFirstTeam(hub.postgres)
        await insertHogFunctionTemplate(hub.postgres, WORKFLOW_TEMPLATE)
        deps = createCdpConsumerDeps(hub)
        queue = new CyclotronJobQueuePostgresV2(hub.CONSUMER_BATCH_SIZE, hub)
        await queue.startAsProducer()
        mockFetch.mockClear()
        worker = undefined
    })

    afterEach(async () => {
        await worker?.stop()
        await queue.stopProducer()
        await closeHub(hub)
    })

    async function storeProgram(entry: CorpusEntry): Promise<void> {
        const row = asColumns(entry.stored[SCENARIOS[entry.scenario].table])
        if (entry.scenario === 'destination') {
            await insertHogFunction(hub.postgres, team.id, row)
            return
        }
        const flow = new FixtureHogFlowBuilder().withTeamId(team.id).withStatus('active').build()
        await insertHogFlow(hub.postgres, { ...flow, ...row } as HogFlow)
    }

    async function captureEvent(): Promise<void> {
        const events = new CdpEventsConsumer(hub, deps, { hogQueue: queue, hogflowQueue: queue })
        const globals = createHogExecutionGlobals({
            project: { id: team.id } as any,
            event: {
                uuid: 'b3a1fe86-b10c-43cc-acaf-d208977608d0',
                event: '$pageview',
                distinct_id: 'stored-program-distinct-id',
                properties: EVENT_PROPERTIES,
                timestamp: '2024-09-03T09:00:00Z',
            } as any,
        })
        await (
            await events.processBatch([globals])
        ).backgroundTask
    }

    async function startWorker(scenario: Scenario): Promise<void> {
        worker =
            scenario === 'destination'
                ? new CdpCyclotronWorker(hub, deps, queue, 'hog')
                : new CdpCyclotronWorkerHogFlow(hub, deps, queue)
        await worker.start()
    }

    async function jobStatuses(): Promise<string[]> {
        const { rows } = await cyclotronPool.query(`SELECT status FROM cyclotron_jobs`)
        return rows.map((row) => row.status)
    }

    describe.each(readCorpus())('$file', ({ entry }) => {
        it('runs on the current code and sends the request its program builds', async () => {
            await storeProgram(entry)

            await captureEvent()
            await startWorker(entry.scenario)

            await waitForExpect(async () => expect(await jobStatuses()).toEqual(['completed']), 10000)
            expect(deliveredRequests()).toEqual([SCENARIOS[entry.scenario].delivers])
        })
    })
})
