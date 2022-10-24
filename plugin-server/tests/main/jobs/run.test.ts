import { RetryError } from '@posthog/plugin-scaffold'
import Redis from 'ioredis'
import { KafkaJSError } from 'kafkajs'
import { Pool } from 'pg'

import { insertRow } from '../../..//tests/helpers/sql'
import { Hub, Plugin, PluginConfig } from '../../../src/types'
import { createHub } from '../../../src/utils/db/hub'
import { UUIDT } from '../../../src/utils/utils'
import { setupPlugins } from '../../../src/worker/plugins/setup'
import { workerTasks } from '../../../src/worker/tasks'

describe('runNow', () => {
    let hub: Hub
    let redis: Redis.Redis
    let closeHub: () => Promise<void>

    beforeAll(async () => {
        ;[hub, closeHub] = await createHub()
        redis = await hub.redisPool.acquire()
    })

    afterAll(async () => {
        await hub.redisPool.release(redis)
        await closeHub()
    })

    test('fails on produce errors', async () => {
        // To ensure that producer errors are retried and not swallowed, we need
        // to ensure that these are bubbled up to the main consumer loop.
        const organizationId = await createOrganization(hub.postgres)
        const plugin = await createPlugin(hub.postgres, {
            organization_id: organizationId,
            name: 'runEveryMinute plugin',
            plugin_type: 'source',
            is_global: false,
            source__index_ts: `
                export async function onEvent(event, { jobs }) {
                    await jobs.test().runNow()
                }

                export const jobs = {
                    test: async () => {}
                }
            `,
        })

        const teamId = await createTeam(hub.postgres, organizationId)
        await createAndReloadPluginConfig(hub.postgres, teamId, plugin.id, redis)
        await setupPlugins(hub)

        jest.spyOn(hub.kafkaProducer.producer, 'send').mockImplementation(() => {
            return Promise.reject(new KafkaJSError('Failed to produce'))
        })

        await expect(
            workerTasks.runAsyncHandlersEventPipeline(hub, {
                event: {
                    distinctId: 'asdf',
                    ip: '',
                    teamId: teamId,
                    event: 'some event',
                    properties: {},
                    eventUuid: new UUIDT().toString(),
                },
            })
        ).rejects.toEqual(new KafkaJSError('Failed to produce'))
    })

    test('retry on RetryError', async () => {
        // To ensure that producer errors are retried and not swallowed, we need
        // to ensure that these are bubbled up to the main consumer loop.
        const organizationId = await createOrganization(hub.postgres)
        const plugin = await createPlugin(hub.postgres, {
            organization_id: organizationId,
            name: 'runEveryMinute plugin',
            plugin_type: 'source',
            is_global: false,
            source__index_ts: `
                export async function onEvent(event, { jobs }) {
                    await jobs.test().runNow()
                }

                export const jobs = {
                    test: async () => {}
                }
            `,
        })

        const teamId = await createTeam(hub.postgres, organizationId)
        await createAndReloadPluginConfig(hub.postgres, teamId, plugin.id, redis)
        await setupPlugins(hub)

        jest.spyOn(hub.kafkaProducer.producer, 'send').mockImplementationOnce(() => {
            return Promise.reject(new RetryError('retry error'))
        })

        const event = {
            distinctId: 'asdf',
            ip: '',
            teamId: teamId,
            event: 'some event',
            properties: {},
            eventUuid: new UUIDT().toString(),
        }
        expect(
            workerTasks.runAsyncHandlersEventPipeline(hub, {
                event,
            })
        ).toEqual(event)
    })
})

export const createPlugin = async (pgClient: Pool, plugin: Omit<Plugin, 'id'>) => {
    return await insertRow(pgClient, 'posthog_plugin', {
        ...plugin,
        config_schema: {},
        from_json: false,
        from_web: false,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        is_preinstalled: false,
        capabilities: {},
    })
}

export const createPluginConfig = async (
    pgClient: Pool,
    pluginConfig: Omit<PluginConfig, 'id' | 'created_at' | 'enabled' | 'order' | 'config' | 'has_error'>
) => {
    return await insertRow(pgClient, 'posthog_pluginconfig', {
        ...pluginConfig,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        enabled: true,
        order: 0,
        config: {},
    })
}

export const createAndReloadPluginConfig = async (
    pgClient: Pool,
    teamId: number,
    pluginId: number,
    redis: Redis.Redis
) => {
    const pluginConfig = await createPluginConfig(pgClient, { team_id: teamId, plugin_id: pluginId })
    // Make sure the plugin server reloads the newly created plugin config.
    // TODO: avoid reaching into the pluginsServer internals and rather use
    // the pubsub mechanism to trigger this.
    await redis.publish('reload-plugins', '')
    return pluginConfig
}

export const createOrganization = async (pgClient: Pool) => {
    const organizationId = new UUIDT().toString()
    await insertRow(pgClient, 'posthog_organization', {
        id: organizationId,
        name: 'TEST ORG',
        plugins_access_level: 9,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        personalization: '{}', // DEPRECATED
        setup_section_2_completed: true, // DEPRECATED
        for_internal_metrics: false,
        available_features: [],
        domain_whitelist: [],
        is_member_join_email_enabled: false,
        slug: Math.round(Math.random() * 20000),
    })
    return organizationId
}

export const createTeam = async (pgClient: Pool, organizationId: string) => {
    const team = await insertRow(pgClient, 'posthog_team', {
        organization_id: organizationId,
        app_urls: [],
        name: 'TEST PROJECT',
        event_names: [],
        event_names_with_usage: [],
        event_properties: [],
        event_properties_with_usage: [],
        event_properties_numerical: [],
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        anonymize_ips: false,
        completed_snippet_onboarding: true,
        ingested_event: true,
        uuid: new UUIDT().toString(),
        session_recording_opt_in: true,
        plugins_opt_in: false,
        opt_out_capture: false,
        is_demo: false,
        api_token: new UUIDT().toString(),
        test_account_filters: [],
        timezone: 'UTC',
        data_attributes: ['data-attr'],
        person_display_name_properties: [],
        access_control: false,
    })
    return team.id
}
