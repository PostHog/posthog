import { Reader } from '@maxmind/geoip2-node'
import fs from 'fs/promises'
import * as schedule from 'node-schedule'

import { PluginsServerConfig } from '~/types'

import { defaultConfig } from '../config/config'
import {
    GeoIPService,
    GeoIPServiceComponent,
    GeoIp,
    MMDB_LOAD_TIMEOUT_MS,
    MmdbLoadTimeoutError,
    MmdbMode,
    geoipServerDefaultMode,
    resolveCdpMmdbMode,
} from './geoip'
import { logger } from './logger'

describe('GeoIp', () => {
    let service: GeoIPService
    let config: PluginsServerConfig

    jest.setTimeout(1000)

    beforeEach(() => {
        config = { ...defaultConfig }
        service = new GeoIPService(config.MMDB_FILE_LOCATION)
    })

    afterEach(() => {
        jest.restoreAllMocks()
        jest.useRealTimers()
    })

    const commonCheck = (geoip: GeoIp) => {
        expect(geoip.city('216.160.83.56')).toMatchObject({ city: { names: { en: 'Milton' } } })
    }

    describe('from disk', () => {
        it('should load the mmdb from disk if set', async () => {
            const geoip = await service.get()
            expect(geoip).toBeTruthy()
            commonCheck(geoip)
        })

        it('should return null for lookups if MMDB file is missing', async () => {
            service = new GeoIPService('non-existent-file.mmdb')
            const geoip = await service.get()
            expect(geoip).toBeTruthy()
            expect(geoip.city('216.160.83.56')).toBeNull()
        })

        it('should only load mmdb from disk once', async () => {
            const getSpy = jest.spyOn(Reader, 'open')
            const res = await Promise.all([service.get(), service.get()])
            expect(getSpy).toHaveBeenCalledTimes(1)

            commonCheck(res[0])
            commonCheck(res[1])
        })

        it('should not read the MMDB or warn if disabled', async () => {
            const openSpy = jest.spyOn(Reader, 'open')
            const warnSpy = jest.spyOn(logger, 'warn')
            service = new GeoIPService('non-existent-file.mmdb', 'disabled')

            const geoip = await service.get()

            expect(geoip.city('216.160.83.56')).toBeNull()
            expect(service.mmdbSource).toEqual({ kind: 'disabled' })
            expect(openSpy).not.toHaveBeenCalled()
            expect(warnSpy).not.toHaveBeenCalled()
        })

        it('should fail the initial load if reading the MMDB hangs', async () => {
            jest.useFakeTimers()
            jest.spyOn(Reader, 'open').mockReturnValue(new Promise<never>(() => {}))

            const promise = service.get()
            const assertion = expect(promise).rejects.toThrow(MmdbLoadTimeoutError)
            await jest.advanceTimersByTimeAsync(MMDB_LOAD_TIMEOUT_MS)
            await assertion
        })
    })

    describe('component', () => {
        it.each<{ mode: MmdbMode }>([{ mode: 'required' }, { mode: 'optional' }])(
            'starts with the mmdb loaded when the mode is $mode',
            async ({ mode }) => {
                const started = await new GeoIPServiceComponent(config.MMDB_FILE_LOCATION, mode).start()
                commonCheck(await started.value.get())
                await started.stop()
            }
        )

        it('fails to start if the MMDB is required and missing', async () => {
            await expect(new GeoIPServiceComponent('non-existent-file.mmdb', 'required').start()).rejects.toThrow(
                'GeoIP is required, but the MMDB could not be loaded from non-existent-file.mmdb'
            )
        })

        it('cancels the hourly refresh on stop', async () => {
            const nodeEnv = process.env.NODE_ENV
            process.env.NODE_ENV = 'dev'
            const jobsBefore = Object.keys(schedule.scheduledJobs).length
            try {
                const started = await new GeoIPServiceComponent(config.MMDB_FILE_LOCATION, 'optional').start()
                expect(Object.keys(schedule.scheduledJobs)).toHaveLength(jobsBefore + 1)

                await started.stop()

                expect(Object.keys(schedule.scheduledJobs)).toHaveLength(jobsBefore)
            } finally {
                process.env.NODE_ENV = nodeEnv
            }
        })
    })

    describe('mode', () => {
        it.each<{ cdpMmdbEnabled: string; cdpDefault: MmdbMode; expected: MmdbMode }>([
            { cdpMmdbEnabled: '', cdpDefault: 'optional', expected: 'optional' },
            { cdpMmdbEnabled: ' ', cdpDefault: 'disabled', expected: 'disabled' },
            { cdpMmdbEnabled: 'true', cdpDefault: 'disabled', expected: 'required' },
            { cdpMmdbEnabled: ' true', cdpDefault: 'disabled', expected: 'required' },
            { cdpMmdbEnabled: '1', cdpDefault: 'optional', expected: 'required' },
            { cdpMmdbEnabled: 'false', cdpDefault: 'optional', expected: 'disabled' },
            { cdpMmdbEnabled: 'off ', cdpDefault: 'optional', expected: 'disabled' },
        ])(
            'resolves CDP_MMDB_ENABLED="$cdpMmdbEnabled" with default $cdpDefault to $expected',
            ({ cdpMmdbEnabled, cdpDefault, expected }) => {
                expect(resolveCdpMmdbMode(cdpMmdbEnabled, cdpDefault)).toBe(expected)
            }
        )

        it('rejects a CDP_MMDB_ENABLED value that is not a boolean', () => {
            expect(() => resolveCdpMmdbMode('ture', 'optional')).toThrow(
                "CDP_MMDB_ENABLED must be true, false or empty, got 'ture'"
            )
        })

        it.each<{ cloudDeployment: string | null; expected: MmdbMode }>([
            { cloudDeployment: 'US', expected: 'required' },
            { cloudDeployment: 'EU', expected: 'required' },
            { cloudDeployment: 'DEV', expected: 'required' },
            { cloudDeployment: 'E2E', expected: 'optional' },
            { cloudDeployment: null, expected: 'optional' },
        ])('defaults a GeoIP server on $cloudDeployment to $expected', ({ cloudDeployment, expected }) => {
            expect(geoipServerDefaultMode(cloudDeployment)).toBe(expected)
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

        it('should retry the refresh if the initial metadata read timed out', async () => {
            // Metadata read times out at startup while the mmdb itself loads fine
            const realReadFile = fs.readFile
            jest.spyOn(fs, 'readFile').mockImplementation(((path: any, ...args: any[]) =>
                String(path).endsWith('.json')
                    ? Promise.reject(new MmdbLoadTimeoutError(String(path)))
                    : (realReadFile as any)(path, ...args)) as any)

            const geoip = await service.get()
            commonCheck(geoip)
            expect(service['_mmdbMetadata']).toBeUndefined()

            // The mount recovered: metadata is readable again, so the refresh must run
            jest.spyOn(service as any, 'loadMmdbMetadata').mockResolvedValue({
                date: '2025-01-02',
            })
            await service['backgroundRefreshMmdb']()

            expect(jest.mocked(service['loadMmdb'])).toHaveBeenCalledTimes(2)
            expect(service['_mmdbMetadata']).toEqual({ date: '2025-01-02' })
        })

        it('should keep the existing mmdb if the refresh times out', async () => {
            jest.spyOn(service as any, 'loadMmdbMetadata').mockResolvedValue({
                date: '2025-01-01',
            })
            const geoip = await service.get()
            commonCheck(geoip)

            jest.spyOn(service as any, 'loadMmdbMetadata').mockResolvedValue({
                date: '2025-01-02',
            })
            jest.spyOn(service as any, 'loadMmdb').mockRejectedValue(new MmdbLoadTimeoutError('some-location'))

            // Simulate the background refresh: it must not throw, and the loaded db keeps serving
            await service['backgroundRefreshMmdb']()
            expect(service['_mmdbMetadata']).toEqual({ date: '2025-01-01' })
            commonCheck(geoip)
        })
    })
})
