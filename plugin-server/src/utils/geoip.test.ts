import { Reader } from '@maxmind/geoip2-node'

import { defaultConfig } from '../config/config'
import { PluginsServerConfig } from '../types'
import { GeoIp, GeoIPService } from './geoip'

describe('GeoIp', () => {
    let service: GeoIPService
    let config: PluginsServerConfig

    jest.setTimeout(1000)
    beforeEach(() => {
        config = { ...defaultConfig }
        service = new GeoIPService(config)
    })

    const commonCheck = (geoip: GeoIp) => {
        expect(geoip.city('12.87.118.0')).toMatchObject({ city: { names: { en: 'Cleveland' } } })
    }

    describe('from disk', () => {
        it('should load the mmdb from disk if set', async () => {
            const geoip = await service.get()
            expect(geoip).toBeDefined()
            commonCheck(geoip)
        })

        it('should throw if it could not be loaded from disk if set', async () => {
            config.MMDB_FILE_LOCATION = 'non-existent-file.mmdb'
            await expect(service.get()).rejects.toThrow()
        })

        it('should load only load mmdb from disk once', async () => {
            const getSpy = jest.spyOn(Reader, 'open')
            const res = await Promise.all([service.get(), service.get()])
            expect(getSpy).toHaveBeenCalledTimes(1)

            commonCheck(res[0])
            commonCheck(res[1])
        })
    })
})
