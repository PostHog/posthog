
import AdmZip from 'adm-zip'
import { Pool } from 'pg'
import { defaultConfig } from '../src/config/config'
import { PluginServerMode, ServerInstance, startPluginsServer } from '../src/main/pluginsServer'
import { LogLevel, PluginsServerConfig } from '../src/types'
import { UUIDT } from '../src/utils/utils'
import { makePiscina } from '../src/worker/piscina'
import { DummyPostHog } from '../src/worker/vm/extensions/posthog'
import { writeToFile } from '../src/worker/vm/extensions/test-utils'
import { resetGraphileSchema } from './helpers/graphile'
import { insertRow } from './helpers/sql'

const mS3WrapperInstance = {
    upload: jest.fn(),
    getObject: jest.fn(),
    deleteObject: jest.fn(),
    listObjectsV2: jest.fn(),
    mockClear: () => {
        mS3WrapperInstance.upload.mockClear()
        mS3WrapperInstance.getObject.mockClear()
        mS3WrapperInstance.deleteObject.mockClear()
        mS3WrapperInstance.listObjectsV2.mockClear()
    },
}

jest.mock('../src/utils/db/s3-wrapper', () => {
    return { S3Wrapper: jest.fn(() => mS3WrapperInstance) }
})
jest.mock('../src/utils/db/sql')
jest.mock('../src/utils/kill')
jest.setTimeout(60000) // 60 sec timeout


const createConfig = (config: Partial<PluginsServerConfig>): PluginsServerConfig => ({
    ...defaultConfig,
    WORKER_CONCURRENCY: 2,
    LOG_LEVEL: LogLevel.Debug,
    ...config,
})

const initTest = async (
    config: Partial<PluginsServerConfig>,
    resetSchema = true
): Promise<PluginsServerConfig> => {
    const createdConfig = createConfig(config)
    if (resetSchema) {
        await resetGraphileSchema(createdConfig)
    }
    return createdConfig
}


const { console: testConsole } = writeToFile


describe("ingest worker job handling", () => {

    let ingest_worker: ServerInstance
    let ingest_posthog: DummyPostHog


    beforeAll(async () => {
        const config = await initTest({ JOB_QUEUES: 'graphile' })
        ingest_worker = await startPluginsServer(config, makePiscina, PluginServerMode.Ingestion)
    })

    afterAll(async () => {
        await ingest_worker?.stop()
    })

    test("ingest server should not consume jobs to run", async () => {
        // Add in a basic plugin that we can validate if the job has been run
        const testPluginJs = `
            import { console } from 'test-utils/write-to-file'

            export const jobs = {
                logReply: (payload, meta) => {
                    console.log('reply')
                }
            }
        `

        const teamId = await createTeam(ingest_worker.hub.postgres)
        const pluginId = await createPlugin(ingest_worker.hub.postgres, testPluginJs)
        const pluginConfigId = await createPluginConfig(ingest_worker.hub.postgres, {teamId, pluginId})

        ingest_worker.hub.jobQueueManager.enqueue({
            pluginConfigTeam: pluginConfigId,
            pluginConfigId: pluginId,
            type: 'logReply',
            timestamp: 123,
            payload: {
            },
        })

        expect(testConsole.read()).toEqual([])
    })
})


describe("apps runner job handling", () => {
    let apps_runner: ServerInstance

    beforeAll(async () => {
        const config = await initTest({ JOB_QUEUES: 'graphile' })
        apps_runner = await startPluginsServer(config, makePiscina, PluginServerMode.Runner)
    })

    afterAll(async () => {
        await apps_runner?.stop()
    })

    test("apps runner should consume jobs to run", async () => {
        // Add in a basic plugin that we can validate if the job has been run
        const testPluginJs = `
            import { console } from 'test-utils/write-to-file'

            export const jobs = {
                logReply: (payload, meta) => {
                    console.log('reply')
                }
            }
        `

        const teamId = await createTeam(apps_runner.hub.postgres)
        const pluginId = await createPlugin(apps_runner.hub.postgres, testPluginJs)
        const pluginConfigId = await createPluginConfig(apps_runner.hub.postgres, {teamId, pluginId})

        apps_runner.hub.jobQueueManager.enqueue({
            pluginConfigTeam: pluginConfigId,
            pluginConfigId: pluginId,
            type: 'logReply',
            timestamp: 123,
            payload: {
            },
        })

        expect(testConsole.read()).toEqual(['reply'])
    })
})


const createPluginConfig = async (postgres: Pool, {teamId, pluginId}: {teamId: number, pluginId: number}) => {
    const pluginConfig = {
        team_id: teamId,
        plugin_id: pluginId,
        enabled: true,
        order: 0,
        config: {},
        error: undefined,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
    }

    return  await insertRow(postgres, 'posthog_pluginconfig', pluginConfig)

}

const createPlugin = async (postgres: Pool, testPluginJs: string) => {
    const plugin = {
        organization_id: 'ca30f2ec-e9a4-4001-bf27-3ef194086068',
        plugin_type: 'custom',
        name: 'test-plugin',
        description: 'Ingest GeoIP data via MaxMind',
        url: 'https://www.npmjs.com/package/posthog-maxmind-plugin',
        config_schema: {},
        archive: createZipBuffer('test-plugin', { indexJs: testPluginJs }),

        error: undefined,
        from_json: false,
        from_web: false,
        is_global: false,
        is_preinstalled: false,
        is_stateless: false,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        capabilities: {}, // inferred on setup
        metrics: {},
    }

    return await insertRow(postgres, 'posthog_plugin', plugin)
}


const createTeam = async (postgres: Pool) => {
    return await insertRow(postgres, 'posthog_team', {
        organization_id: 'ca30f2ec-e9a4-4001-bf27-3ef194086068',
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
        access_control: false,
    })
}



const createZipBuffer = (name: string, { indexJs, pluginJson }: { indexJs?: string; pluginJson?: string }): Buffer => {
    const zip = new AdmZip()
    if (indexJs) {
        zip.addFile('testplugin/index.js', Buffer.alloc(indexJs.length, indexJs))
    }
    if (pluginJson) {
        zip.addFile('testplugin/plugin.json', Buffer.alloc(pluginJson.length, pluginJson))
    } else {
        zip.addFile(
            'testplugin/plugin.json',
            Buffer.from(
                JSON.stringify({
                    name,
                    description: 'just for testing',
                    url: 'http://example.com/plugin',
                    config: {},
                    main: 'index.js',
                })
            )
        )
    }
    return zip.toBuffer()
}
