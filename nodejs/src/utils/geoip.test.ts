import { Reader } from '@maxmind/geoip2-node'

import { defaultConfig } from '../config/config'
import { PluginsServerConfig } from '../types'
import { GeoIPService, GeoIp } from './geoip'

describe('GeoIp', () => {
    let service: GeoIPService
    let config: PluginsServerConfig

    jest.setTimeout(1000)

    beforeEach(() => {
        config = { ...defaultConfig }
        service = new GeoIPService(config)
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    const commonCheck = (geoip: GeoIp) => {
        expect(geoip.city('12.87.118.0')).toMatchObject({ city: { names: { en: 'Cleveland' } } })
    }

    describe('from disk', () => {
        it('should load the mmdb from disk if set', async () => {
            const geoip = await service.get()
            expect(geoip).toBeTruthy()
            commonCheck(geoip)
        })

        it('should throw if it could not be loaded from disk if set', async () => {
            config.MMDB_FILE_LOCATION = 'non-existent-file.mmdb'
            await expect(service.get()).rejects.toThrow()
        })

        it('should only load mmdb from disk once', async () => {
            const getSpy = jest.spyOn(Reader, 'open')
            const res = await Promise.all([service.get(), service.get()])
            expect(getSpy).toHaveBeenCalledTimes(1)

            commonCheck(res[0])
            commonCheck(res[1])
        })
    })

    describe('background refresh', () => {
        beforeEach(() => {
            jest.spyOn(service as any, 'loadMmdb')
        })

        it('should not refresh the mmdb if there is no metadata', async () => {
            jest.spyOn(service as any, 'loadMmdbMetadata').mockResolvedValue(undefined)
            const geoip = await service.get()
            expect(geoip).toBeTruthy()
            expect(service['_mmdbMetadata']).toBeUndefined()
            expect(jest.mocked(service['loadMmdb'])).toHaveBeenCalledTimes(1)

            jest.spyOn(service as any, 'loadMmdbMetadata').mockResolvedValue({
                date: '2025-01-01',
            })

            // Simulate the background refresh
            await service['backgroundRefreshMmdb']()
            expect(jest.mocked(service['loadMmdb'])).toHaveBeenCalledTimes(1)
        })

        it('should not refresh the mmdb if the metadata is the same', async () => {
            jest.spyOn(service as any, 'loadMmdbMetadata').mockResolvedValue({
                date: '2025-01-01',
            })
            const geoip = await service.get()
            expect(geoip).toBeTruthy()
            expect(service['_mmdbMetadata']).toEqual({ date: '2025-01-01' })
            expect(jest.mocked(service['loadMmdb'])).toHaveBeenCalledTimes(1)

            // Simulate the background refresh
            await service['backgroundRefreshMmdb']()
            expect(jest.mocked(service['loadMmdb'])).toHaveBeenCalledTimes(1)
        })

        it('should refresh the mmdb if the metadata is different', async () => {
            jest.spyOn(service as any, 'loadMmdbMetadata').mockResolvedValue({
                date: '2025-01-01',
            })
            const geoip = await service.get()
            expect(geoip).toBeTruthy()
            expect(service['_mmdbMetadata']).toEqual({ date: '2025-01-01' })
            expect(jest.mocked(service['loadMmdb'])).toHaveBeenCalledTimes(1)

            jest.spyOn(service as any, 'loadMmdbMetadata').mockResolvedValue({
                date: '2025-01-02',
            })

            // Simulate the background refresh
            await service['backgroundRefreshMmdb']()
            expect(jest.mocked(service['loadMmdb'])).toHaveBeenCalledTimes(2)
            expect(service['_mmdbMetadata']).toEqual({ date: '2025-01-02' })
        })
    })
})
