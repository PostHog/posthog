import { buildStringMatcher } from '../../../src/config/config'
import { KAFKA_EVENTS_PLUGIN_INGESTION } from '../../../src/config/kafka-topics'
import {
    eachBatchParallelIngestion,
    IngestionOverflowMode,
    splitIngestionBatch,
} from '../../../src/main/ingestion-queues/batch-processing/each-batch-ingestion'
import { eachBatchAppsOnEventHandlers } from '../../../src/main/ingestion-queues/batch-processing/each-batch-onevent'
import {
    eachBatchWebhooksHandlers,
    eachMessageWebhooksHandlers,
    groupIntoBatchesByUsage,
} from '../../../src/main/ingestion-queues/batch-processing/each-batch-webhooks'
import * as batchProcessingMetrics from '../../../src/main/ingestion-queues/batch-processing/metrics'
import {
    ClickHouseTimestamp,
    ClickHouseTimestampSecondPrecision,
    Hub,
    ISOTimestamp,
    PostIngestionEvent,
    PropertyOperator,
    RawClickHouseEvent,
} from '../../../src/types'
import { createHub } from '../../../src/utils/db/hub'
import { PostgresUse } from '../../../src/utils/db/postgres'
import { ActionManager } from '../../../src/worker/ingestion/action-manager'
import { ActionMatcher } from '../../../src/worker/ingestion/action-matcher'
import { GroupTypeManager } from '../../../src/worker/ingestion/group-type-manager'
import { HookCommander } from '../../../src/worker/ingestion/hooks'
import { runOnEvent } from '../../../src/worker/plugins/run'
import { pluginConfig39 } from '../../helpers/plugins'
import { resetTestDatabase } from '../../helpers/sql'

jest.mock('../../../src/worker/plugins/run')

jest.mock('../../../src/worker/ingestion/event-pipeline/runAsyncHandlersStep', () => {
    const originalModule = jest.requireActual('../../../src/worker/ingestion/event-pipeline/runAsyncHandlersStep')
    return {
        ...originalModule,
        processWebhooksStep: jest.fn(originalModule.processWebhooksStep),
    }
})
jest.mock('../../../src/utils/status')
jest.mock('./../../../src/worker/ingestion/utils')

const runEventPipeline = jest.fn().mockResolvedValue('default value')

jest.mock('./../../../src/worker/ingestion/event-pipeline/runner', () => ({
    EventPipelineRunner: jest.fn().mockImplementation(() => ({
        runEventPipeline: runEventPipeline,
    })),
}))

const event: PostIngestionEvent = {
    eventUuid: 'uuid1',
    distinctId: 'my_id',
    teamId: 2,
    timestamp: '2020-02-23T02:15:00.000Z' as ISOTimestamp,
    event: '$pageview',
    properties: {},
    elementsList: undefined,
    person_id: 'F99FA0A1-E0C2-4CFE-A09A-4C3C4327A4CC',
    person_created_at: '2020-02-20T02:15:00.000Z' as ISOTimestamp,
    person_properties: {},
}

const clickhouseEvent: RawClickHouseEvent = {
    event: '$pageview',
    properties: JSON.stringify({
        $ip: '127.0.0.1',
        $groups: {
            organization: 'org_posthog',
        },
    }),
    uuid: 'uuid1',
    elements_chain: '',
    timestamp: '2020-02-23 02:15:00.00' as ClickHouseTimestamp,
    team_id: 2,
    distinct_id: 'my_id',
    created_at: '2020-02-23 02:15:00.00' as ClickHouseTimestamp,
    person_id: 'F99FA0A1-E0C2-4CFE-A09A-4C3C4327A4CC',
    person_created_at: '2020-02-20 02:15:00' as ClickHouseTimestampSecondPrecision, // Match createEvent ts format
    person_properties: '{}',
    group0_properties: JSON.stringify({ name: 'PostHog' }),
}

describe('eachMessageWebhooksHandlers', () => {
    let hub: Hub
    let closeHub: () => Promise<void>

    beforeEach(async () => {
        ;[hub, closeHub] = await createHub()
        console.warn = jest.fn() as any
        await resetTestDatabase()

        await hub.db.postgres.query(
            PostgresUse.COMMON_WRITE,
            `UPDATE posthog_team SET slack_incoming_webhook = 'https://webhook.example.com/'`,
            [],
            'testTag'
        )
    })

    afterEach(async () => {
        await closeHub()
    })

    it('calls runWebhooksHandlersEventPipeline', async () => {
        const actionManager = new ActionManager(hub.postgres)
        const actionMatcher = new ActionMatcher(hub.postgres, actionManager)
        const hookCannon = new HookCommander(
            hub.postgres,
            hub.teamManager,
            hub.organizationManager,
            hub.rustyHook,
            hub.appMetrics,
            hub.EXTERNAL_REQUEST_TIMEOUT_MS
        )
        const groupTypeManager = new GroupTypeManager(hub.postgres, hub.teamManager)
        groupTypeManager['groupTypesCache'].set(2, [
            {
                organization: 0,
            },
            Date.now(),
        ])

        actionManager['ready'] = true
        actionManager['actionCache'] = {
            2: {
                1: {
                    id: 1,
                    team_id: 2,
                    name: 'Test Action',
                    deleted: false,
                    post_to_slack: true,
                    slack_message_format:
                        '[action.name] was triggered by [person] in organization [groups.organization]',
                    is_calculating: false,
                    steps: [
                        {
                            id: 913,
                            action_id: 69,
                            tag_name: null,
                            text: null,
                            text_matching: null,
                            href: null,
                            href_matching: null,
                            selector: null,
                            url: null,
                            url_matching: null,
                            name: null,
                            event: '$pageview',
                            properties: [],
                        },
                    ],
                    hooks: [],
                },
            },
        }

        const matchSpy = jest.spyOn(actionMatcher, 'match')
        const postWebhookSpy = jest.spyOn(hookCannon.rustyHook, 'enqueueIfEnabledForTeam')

        await eachMessageWebhooksHandlers(clickhouseEvent, actionMatcher, hookCannon, groupTypeManager)

        // NOTE: really it would be nice to verify that fire has been called
        // on hookCannon, but that would require a little more setup, and it
        // is at the least testing a little bit more than we were before.
        expect(matchSpy).toHaveBeenCalledWith({
            ...event,
            groups: {
                organization: {
                    index: 0,
                    type: 'organization',
                    key: 'org_posthog',
                    properties: { name: 'PostHog' },
                },
            },
            properties: {
                $ip: '127.0.0.1',
                $groups: {
                    organization: 'org_posthog',
                },
            },
        })

        expect(postWebhookSpy).toHaveBeenCalledTimes(1)
        expect(JSON.parse(postWebhookSpy.mock.calls[0][0].webhook.body)).toMatchInlineSnapshot(`
            Object {
              "text": "[Test Action](/project/2/action/1) was triggered by [my\\\\_id](/project/2/person/my\\\\_id) in organization [PostHog](/project/2/groups/0/org\\\\_posthog)",
            }
        `)
    })
})
