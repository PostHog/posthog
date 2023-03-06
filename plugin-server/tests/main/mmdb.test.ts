import { ReaderModel } from '@maxmind/geoip2-node'
import * as fetch from 'node-fetch'

import { ServerInstance, startPluginsServer } from '../../src/main/pluginsServer'
import { fetchIpLocationInternally } from '../../src/worker/mmdb'
import { makePiscina } from '../../src/worker/piscina'
import { resetTestDatabase } from '../helpers/sql'

jest.mock('../../src/utils/status')

async function resetTestDatabaseWithMmdb(): Promise<void> {
    await resetTestDatabase(undefined, undefined)
}

describe('mmdb', () => {
    let serverInstance: ServerInstance

    jest.setTimeout(100_000)

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

        await expect(
            async () => await fetchIpLocationInternally('89.160.20.129', serverInstance.hub)
        ).rejects.toThrowError('IP location capabilities are not available in this PostHog instance!')
    })

    test('fresh MMDB is downloaded if not cached and works', async () => {
        await resetTestDatabase()

        serverInstance = await startPluginsServer({ DISABLE_MMDB: false }, makePiscina)

        expect(serverInstance.hub.DISABLE_MMDB).toBeFalsy()

        expect(fetch).toHaveBeenCalledWith('https://mmdbcdn.posthog.net/', { compress: false })
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
})
