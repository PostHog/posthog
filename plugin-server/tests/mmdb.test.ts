import { ReaderModel } from '@maxmind/geoip2-node'
import { readFileSync } from 'fs'
import { DateTime } from 'luxon'
import * as fetch from 'node-fetch'
import { join } from 'path'

import { ServerInstance, startPluginsServer } from '../src/main/pluginsServer'
import { fetchIpLocationInternally } from '../src/worker/mmdb'
import { makePiscina } from '../src/worker/piscina'
import { resetTestDatabase } from './helpers/sql'

const mmdbBrotliContents = readFileSync(join(__dirname, 'assets', 'GeoLite2-City-Test.mmdb.br'))

async function resetTestDatabaseWithMmdb(): Promise<void> {
    await resetTestDatabase(undefined, undefined, {
        pluginAttachments: [
            {
                key: '@posthog/mmdb',
                content_type: 'vnd.maxmind.maxmind-db',
                file_name: `GeoLite2-City-${DateTime.local().toISODate()}.mmdb.br`,
                file_size: mmdbBrotliContents.byteLength,
                contents: mmdbBrotliContents,
                team_id: null,
                plugin_config_id: null,
            },
        ],
    })
}

let serverInstance: ServerInstance

jest.setTimeout(30_000)

afterEach(async () => {
    await serverInstance?.stop()
    jest.clearAllMocks()
})

test('no MMDB is used or available if MMDB disabled', async () => {
    await resetTestDatabase()

    serverInstance = await startPluginsServer({ DISABLE_MMDB: true }, makePiscina)

    expect(serverInstance.hub.DISABLE_MMDB).toBeTruthy()

    expect(fetch).not.toHaveBeenCalled()
    expect(serverInstance.mmdb).toBeUndefined()

    await expect(async () => await fetchIpLocationInternally('89.160.20.129', serverInstance.hub)).rejects.toThrowError(
        'IP location capabilities are not available in this PostHog instance!'
    )
})

test('fresh MMDB is downloaded if not cached and works', async () => {
    await resetTestDatabase()

    serverInstance = await startPluginsServer({ DISABLE_MMDB: false }, makePiscina)

    expect(serverInstance.hub.DISABLE_MMDB).toBeFalsy()

    expect(fetch).toHaveBeenCalledWith('https://mmdb.posthog.net/', { compress: false })
    expect(serverInstance.mmdb).toBeInstanceOf(ReaderModel)

    const cityResultDirect = serverInstance.mmdb!.city('89.160.20.129')
    expect(cityResultDirect.city).toBeDefined()
    expect(cityResultDirect.city!.names.en).toStrictEqual('Linköping')

    const cityResultDirectInvalid = await fetchIpLocationInternally('asdfgh', serverInstance.hub)
    expect(cityResultDirectInvalid).toBeNull()

    const cityResultTcp = await fetchIpLocationInternally('89.160.20.129', serverInstance.hub)
    expect(cityResultTcp).toBeTruthy()
    expect(cityResultTcp!.city).toBeDefined()
    expect(cityResultTcp!.city!.names.en).toStrictEqual('Linköping')

    const cityResultTcpInvalid = await fetchIpLocationInternally('asdfgh', serverInstance.hub)
    expect(cityResultTcpInvalid).toBeNull()
})

test('cached MMDB is used and works', async () => {
    await resetTestDatabaseWithMmdb()

    serverInstance = await startPluginsServer({ DISABLE_MMDB: false }, makePiscina)

    expect(serverInstance.hub.DISABLE_MMDB).toBeFalsy()

    expect(fetch).not.toHaveBeenCalled()
    expect(serverInstance.mmdb).toBeInstanceOf(ReaderModel)

    const cityResultDirect = serverInstance.mmdb!.city('89.160.20.129')
    expect(cityResultDirect.city).toBeDefined()
    expect(cityResultDirect.city!.names.en).toStrictEqual('Linköping')

    const cityResultDirectInvalid = await fetchIpLocationInternally('asdfgh', serverInstance.hub)
    expect(cityResultDirectInvalid).toBeNull()

    const cityResultTcp = await fetchIpLocationInternally('89.160.20.129', serverInstance.hub)
    expect(cityResultTcp).toBeTruthy()
    expect(cityResultTcp!.city).toBeDefined()
    expect(cityResultTcp!.city!.names.en).toStrictEqual('Linköping')

    const cityResultTcpInvalid = await fetchIpLocationInternally('asdfgh', serverInstance.hub)
    expect(cityResultTcpInvalid).toBeNull()
})
