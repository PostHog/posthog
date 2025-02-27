import { Reader } from '@maxmind/geoip2-node'

import { defaultConfig } from '../config/config'
import { Config, Hub } from '../types'
import { GeoIp, geoipCompareCounter, GeoIPService } from './geoip'
import { status } from './status'

describe('GeoIp', () => {
    let service: GeoIPService
    let config: Config
    const mockHub = {} as Hub

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
            const geoip = await service.get(mockHub)
            expect(geoip).toBeDefined()
            commonCheck(geoip)
        })

        it('should throw if it could not be loaded from disk if set', async () => {
            config.MMDB_FILE_LOCATION = 'non-existent-file.mmdb'
            await expect(service.get(mockHub)).rejects.toThrow()
        })

        it('should only load mmdb from disk once', async () => {
            const getSpy = jest.spyOn(Reader, 'open')
            const res = await Promise.all([service.get(mockHub), service.get(mockHub)])
            expect(getSpy).toHaveBeenCalledTimes(1)

            commonCheck(res[0])
            commonCheck(res[1])
        })
    })

    describe('comparison mode', () => {
        let workingGeoip: GeoIp
        beforeEach(async () => {
            const workingGeoipService = new GeoIPService({ ...config })
            workingGeoip = await workingGeoipService.get(mockHub)

            config.MMDB_COMPARE_MODE = true
            mockHub.mmdb = {
                city: () => ({
                    city: {
                        geonameId: 1234567890,
                    },
                }),
            } as any

            jest.spyOn(status, 'warn').mockImplementation(() => {})
            jest.spyOn(geoipCompareCounter, 'inc').mockImplementation(() => {})
        })

        it('should return the old mmdb regardless of whether new one loads or not', async () => {
            config.MMDB_FILE_LOCATION = 'non-existent-file.mmdb'
            const geoip = await service.get(mockHub)

            expect(geoip).toBeDefined()
            expect(geoip.city('12.87.118.0')).toMatchInlineSnapshot(`
                {
                  "city": {
                    "geonameId": 1234567890,
                  },
                }
            `)

            // Check that the counter and the log was called
            expect(geoipCompareCounter.inc).toHaveBeenCalledWith({ result: 'different' })
            expect(jest.mocked(status.warn).mock.calls[0]).toMatchInlineSnapshot(`
                [
                  "🌎",
                  "New GeoIP result was different",
                  {
                    "ip": "12.87.118.0",
                    "newGeoipResult": undefined,
                    "oldGeoipResult": "{"geonameId":1234567890}",
                  },
                ]
            `)
        })

        it('should compare the results if different', async () => {
            const geoip = await service.get(mockHub)

            expect(geoip).toBeDefined()
            expect(geoip.city('12.87.118.0')).toMatchInlineSnapshot(`
                {
                  "city": {
                    "geonameId": 1234567890,
                  },
                }
            `)

            // Check that the counter and the log was called
            expect(geoipCompareCounter.inc).toHaveBeenCalledWith({ result: 'different' })
            expect(jest.mocked(status.warn).mock.calls[0]).toMatchInlineSnapshot(`
                [
                  "🌎",
                  "New GeoIP result was different",
                  {
                    "ip": "12.87.118.0",
                    "newGeoipResult": "{"geonameId":5150529,"names":{"de":"Cleveland","en":"Cleveland","es":"Cleveland","fr":"Cleveland","ja":"クリーブランド","pt-BR":"Cleveland","ru":"Кливленд","zh-CN":"克里夫蘭"}}",
                    "oldGeoipResult": "{"geonameId":1234567890}",
                  },
                ]
            `)
        })

        it('should compare the results if the same', async () => {
            const geoip = await service.get(mockHub)
            mockHub.mmdb = {
                city: (ip: string) => workingGeoip.city(ip),
            } as any

            expect(geoip).toBeDefined()
            expect(geoip?.city('12.87.118.0')?.city?.geonameId).toMatchInlineSnapshot(`5150529`)

            // Check that the counter and the log was called
            expect(geoipCompareCounter.inc).toHaveBeenCalledWith({ result: 'same' })
            expect(jest.mocked(status.warn)).not.toHaveBeenCalled()
        })
    })
})
