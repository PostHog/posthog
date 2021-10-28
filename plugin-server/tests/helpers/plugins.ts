import AdmZip from 'adm-zip'
import * as fs from 'fs'
import * as os from 'os'
import * as path from 'path'

import { Plugin, PluginAttachmentDB, PluginConfig } from '../../src/types'

export const commonUserId = 1001
export const commonOrganizationMembershipId = '0177364a-fc7b-0000-511c-137090b9e4e1'
export const commonOrganizationId = 'ca30f2ec-e9a4-4001-bf27-3ef194086068'
export const commonUserUuid = '797757a4-baed-4fa8-b73b-2b6cf0300299'

export const plugin60: Plugin = {
    id: 60,
    organization_id: commonOrganizationId,
    plugin_type: 'custom',
    name: 'test-maxmind-plugin',
    description: 'Ingest GeoIP data via MaxMind',
    url: 'https://www.npmjs.com/package/posthog-maxmind-plugin',
    config_schema: {
        localhostIP: {
            hint: 'Useful if testing locally',
            name: 'IP to use instead of 127.0.0.1',
            type: 'string',
            order: 2,
            default: '',
            required: false,
        },
        maxmindMmdb: {
            hint: 'The "GeoIP2 City" or "GeoLite2 City" database file',
            name: 'GeoIP .mddb database',
            type: 'attachment',
            order: 1,
            markdown:
                'Sign up for a [MaxMind.com](https://www.maxmind.com) account, download and extract the database and then upload the `.mmdb` file below',
            required: true,
        },
    },
    tag: '0.0.2',
    archive: createZipBuffer('test-maxmind-plugin', {
        indexJs:
            'function processEvent (event) { if (event.properties) { event.properties.processed = true } return event }',
    }),
    error: undefined,
    from_json: false,
    from_web: false,
    is_global: false,
    is_preinstalled: false,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    capabilities: {}, // inferred on setup
    metrics: {},
}

export const pluginAttachment1: PluginAttachmentDB = {
    id: 42666,
    key: 'maxmindMmdb',
    content_type: 'application/octet-stream',
    file_name: 'test.txt',
    file_size: 4,
    contents: Buffer.from('test'),
    plugin_config_id: 39,
    team_id: 2,
}

export const pluginConfig39: PluginConfig = {
    id: 39,
    team_id: 2,
    plugin_id: 60,
    enabled: true,
    order: 0,
    config: { localhostIP: '94.224.212.175' },
    error: undefined,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
}

function createZipBuffer(name: string, { indexJs, pluginJson }: { indexJs?: string; pluginJson?: string }): Buffer {
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

export const mockPluginWithArchive = (indexJs: string, pluginJson?: string): Plugin => ({
    ...plugin60,
    archive: createZipBuffer('posthog-maxmind-plugin', { indexJs, pluginJson }),
})

export const makePluginObjects = (
    indexJs = ''
): {
    pluginRows: Omit<Plugin, 'id'>[]
    pluginConfigRows: Omit<PluginConfig, 'id'>[]
    pluginAttachmentRows: Omit<PluginAttachmentDB, 'id'>[]
} => ({
    pluginRows: [mockPluginWithArchive(indexJs)],
    pluginConfigRows: [
        { ...pluginConfig39, created_at: new Date().toISOString(), updated_at: new Date().toISOString() },
    ],
    pluginAttachmentRows: [pluginAttachment1],
})

export function mockPluginTempFolder(indexJs: string, pluginJson?: string): [Plugin, () => void] {
    const folder = fs.mkdtempSync(path.join(os.tmpdir(), 'foo-'))

    fs.writeFileSync(path.join(folder, 'index.js'), indexJs)
    fs.writeFileSync(
        path.join(folder, 'plugin.json'),
        pluginJson ||
            JSON.stringify({
                name: 'posthog-maxmind-plugin',
                description: 'just for testing',
                url: 'http://example.com/plugin',
                config: {},
                main: 'index.js',
            })
    )
    return [
        { ...plugin60, url: `file:${folder}`, archive: null },
        () => {
            fs.rmdirSync(folder, { recursive: true })
        },
    ]
}

export const mockPluginSourceCode = (indexJs: string): Plugin => ({
    ...plugin60,
    archive: null,
    plugin_type: 'source',
    url: undefined,
    source: indexJs,
})

export const plugin70 = {
    ...plugin60,
    id: 70,
    archive: createZipBuffer('test-plugin', {
        indexJs: `
            import { RetryError } from '@posthog/plugin-scaffold'
            export function setupPlugin () { throw new RetryError('I always fail!') }
            export function processEvent (event) { return event }`,
    }),
}
