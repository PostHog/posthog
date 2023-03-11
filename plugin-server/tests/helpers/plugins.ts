import * as fs from 'fs'
import * as os from 'os'
import * as path from 'path'

export const plugin60 = {
    plugin_type: 'custom',
    name: 'test-maxmind-plugin',
    description: 'Ingest GeoIP data via MaxMind',
    url: 'https://www.npmjs.com/package/posthog-maxmind-plugin',
    config_schema: {},
    tag: '0.0.2',
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
    ...mockSourceFileFields('test-maxmind-plugin', {
        indexJs:
            'function processEvent (event) { if (event.properties) { event.properties.processed = true } return event }',
    }),
} as const

export const pluginAttachment1 = {
    key: 'maxmindMmdb',
    content_type: 'application/octet-stream',
    file_name: 'test.txt',
    file_size: 4,
    contents: Buffer.from('test'),
} as const

export const pluginConfig39 = {
    enabled: true,
    order: 0,
    config: { localhostIP: '94.224.212.175' },
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
} as const

export function mockSourceFileFields(name: string, { indexJs, pluginJson }: { indexJs?: string; pluginJson?: string }) {
    const fields = {}
    if (indexJs) {
        fields['source__index_ts'] = indexJs
    }
    fields['source__plugin_json'] =
        pluginJson ||
        JSON.stringify({
            name,
            description: 'just for testing',
            url: 'http://example.com/plugin',
            config: {},
            main: 'index.js',
        })
    return fields
}

export const mockPluginWithSourceFiles = (indexJs: string, pluginJson?: string) => ({
    ...plugin60,
    ...mockSourceFileFields('posthog-maxmind-plugin', { indexJs, pluginJson }),
})

export const makePluginObjects = (indexJs = '') => ({
    pluginRow: mockPluginWithSourceFiles(indexJs),
    pluginConfigRow: { ...pluginConfig39, created_at: new Date().toISOString(), updated_at: new Date().toISOString() },
    pluginAttachmentRow: pluginAttachment1,
})

export function mockPluginTempFolder(indexJs: string, pluginJson?: string) {
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
        { ...plugin60, plugin_type: 'local', url: `file:${folder}` } as const,
        () => {
            fs.rmSync(folder, { recursive: true })
        },
    ] as const
}

export const mockPluginSourceCode = () =>
    ({
        ...plugin60,
        plugin_type: 'source',
        url: undefined,
    } as const)

export const plugin70 = {
    ...plugin60,
    id: 70,
    ...mockSourceFileFields('test-plugin', {
        indexJs: `
            import { RetryError } from '@posthog/plugin-scaffold'
            export function setupPlugin () { throw new RetryError('I always fail!') }
            export function processEvent (event) { return event }`,
    }),
}
