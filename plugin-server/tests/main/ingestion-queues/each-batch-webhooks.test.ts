import { eachMessageWebhooksHandlers } from '../../../src/main/ingestion-queues/batch-processing/each-batch-webhooks'
import {
    ClickHouseTimestamp,
    ClickHouseTimestampSecondPrecision,
    Hub,
    RawClickHouseEvent,
    Team,
} from '../../../src/types'
import { closeHub, createHub } from '../../../src/utils/db/hub'
import { PostgresUse } from '../../../src/utils/db/postgres'
import { parseJSON } from '../../../src/utils/json-parse'
import { getFirstTeam, resetTestDatabase } from '../../helpers/sql'

jest.mock('../../../src/utils/logger')

const kafkaEvent: RawClickHouseEvent = {
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
    person_mode: 'full',
}

describe('eachMessageWebhooksHandlers', () => {
    let hub: Hub
    let team: Team

    beforeEach(async () => {
        hub = await createHub()
        hub.actionManager['ready'] = true
        console.warn = jest.fn() as any
        await resetTestDatabase()
        team = await getFirstTeam(hub)

        await hub.db.postgres.query(
            PostgresUse.COMMON_WRITE,
            `UPDATE posthog_team SET slack_incoming_webhook = 'https://webhook.example.com/'`,
            [],
            'testTag'
        )
        await hub.db.postgres.query(
            PostgresUse.COMMON_WRITE,
            `
            INSERT INTO posthog_group (team_id, group_key, group_type_index, group_properties, created_at, properties_last_updated_at, properties_last_operation, version)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            `,
            [
                2,
                'org_posthog',
                0,
                JSON.stringify({ name: 'PostHog' }),
                new Date().toISOString(),
                JSON.stringify({}),
                JSON.stringify({}),
                1,
            ],
            'upsertGroup'
        )
        await hub.db.postgres.query(
            PostgresUse.COMMON_WRITE,
            `UPDATE posthog_team SET slack_incoming_webhook = 'https://webhook.example.com/'`,
            [],
            'testTag'
        )
    })

    afterEach(async () => {
        await closeHub(hub)
    })

    it('calls runWebhooksHandlersEventPipeline', async () => {
        await hub.groupTypeManager.insertGroupType(team, 'organization', 0)

        hub.organizationManager['availableProductFeaturesCache'].set(2, [
            [{ name: 'Group Analytics', key: 'group_analytics' }],
            Date.now(),
        ])

        hub.actionManager['ready'] = true
        hub.actionManager['actionCache'] = {
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
                            // @ts-expect-error TODO revisit this, but fixing TS for now
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

        const matchSpy = jest.spyOn(hub.actionMatcher, 'match')
        const postWebhookSpy = jest.spyOn(hub.hookCommander.rustyHook, 'enqueueIfEnabledForTeam')

        await eachMessageWebhooksHandlers(hub, kafkaEvent)

        // NOTE: really it would be nice to verify that fire has been called
        // on hookCannon, but that would require a little more setup, and it
        // is at the least testing a little bit more than we were before.
        expect(matchSpy.mock.calls[0][0]).toMatchInlineSnapshot(`
            {
              "distinctId": "my_id",
              "elementsList": undefined,
              "event": "$pageview",
              "eventUuid": "uuid1",
              "groups": {
                "organization": {
                  "index": 0,
                  "key": "org_posthog",
                  "properties": {
                    "name": "PostHog",
                  },
                  "type": "organization",
                },
              },
              "person_created_at": "2020-02-20T02:15:00.000Z",
              "person_id": "F99FA0A1-E0C2-4CFE-A09A-4C3C4327A4CC",
              "person_properties": {},
              "properties": {
                "$groups": {
                  "organization": "org_posthog",
                },
                "$ip": "127.0.0.1",
              },
              "teamId": 2,
              "timestamp": "2020-02-23T02:15:00.000Z",
            }
        `)

        expect(postWebhookSpy).toHaveBeenCalledTimes(1)
        expect(parseJSON(postWebhookSpy.mock.calls[0][0].webhook.body)).toMatchInlineSnapshot(`
            {
              "text": "[Test Action](/project/2/action/1) was triggered by [my\\_id](/project/2/person/my\\_id) in organization [PostHog](/project/2/groups/0/org\\_posthog)",
            }
        `)
    })
})
