import { ReaderModel } from '@maxmind/geoip2-node'
import { readFileSync } from 'fs'
import { DateTime } from 'luxon'
import fetch from 'node-fetch'
import { join } from 'path'

import { Hub, LogLevel } from '../../../src/types'
import { closeHub, createHub } from '../../../src/utils/db/hub'
import { setupMmdb } from '../../../src/worker/plugins/mmdb'
import { resetTestDatabase } from '../../helpers/sql'

// jest.mock('../../src/utils/status')

const mmdbBrotliContents = readFileSync(join(__dirname, '..', '..', 'assets', 'GeoLite2-City-Test.mmdb.br'))

export const cachedMmdbPluginAttachment = {
    key: '@posthog/mmdb',
    content_type: 'vnd.maxmind.maxmind-db',
    file_name: `GeoLite2-City-${DateTime.local().toISODate()}.mmdb.br`,
    file_size: mmdbBrotliContents.byteLength,
    contents: mmdbBrotliContents,
    team_id: null,
    plugin_config_id: null,
}
async function resetTestDatabaseWithMmdb(): Promise<void> {
    await resetTestDatabase(undefined, undefined, {
        pluginAttachments: [cachedMmdbPluginAttachment],
    })
}

async function getCityName(hub: Hub, ipAddress: string) {
    if (hub.mmdb) {
        return Promise.resolve(hub.mmdb.city(ipAddress).city.names.en)
    } else {
        return Promise.reject('geoip database is not ready')
    }
}

describe('mmdb', () => {
    let hub: Hub

    jest.setTimeout(100_000)

    beforeAll(async () => {
        hub = await createHub({ LOG_LEVEL: LogLevel.Warn })
        hub.capabilities.mmdb = true
    })

    afterAll(async () => {
        await closeHub(hub)
        jest.clearAllMocks()
    })

    test('no MMDB is used or available if MMDB disabled', async () => {
        await resetTestDatabase()
        hub.DISABLE_MMDB = true
        await setupMmdb(hub)

        expect(hub.DISABLE_MMDB).toBeTruthy()
        expect(fetch).not.toHaveBeenCalled()
        expect(hub.mmdb).toBeUndefined()
        await expect(async () => {
            await getCityName(hub, '89.160.20.129')
        }).rejects.toStrictEqual('geoip database is not ready')
    })

    test('fresh MMDB is downloaded if not cached and works', async () => {
        await resetTestDatabase()
        hub.DISABLE_MMDB = false

        await setupMmdb(hub)
        expect(hub.DISABLE_MMDB).toBeFalsy()

        expect(fetch).toHaveBeenCalledWith('https://mmdbcdn.posthog.net/', { compress: false })
        expect(hub.mmdb).toBeInstanceOf(ReaderModel)

        expect(await getCityName(hub, '89.160.20.129')).toStrictEqual('Linköping')
        await expect(async () => {
            await getCityName(hub, 'not_an_ip')
        }).rejects.toThrowError('not_an_ip is invalid')
    })

    test('cached MMDB is used and works', async () => {
        await resetTestDatabaseWithMmdb()
        hub.DISABLE_MMDB = false

        await setupMmdb(hub)
        expect(hub.DISABLE_MMDB).toBeFalsy()
        expect(fetch).not.toHaveBeenCalled()
        expect(hub.mmdb).toBeInstanceOf(ReaderModel)
        expect(await getCityName(hub, '89.160.20.129')).toStrictEqual('Linköping')
    })
})
