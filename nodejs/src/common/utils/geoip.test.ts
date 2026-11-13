import { Reader } from '@maxmind/geoip2-node'
import fs from 'fs/promises'

import { PluginsServerConfig } from '~/types'

import { defaultConfig } from '../config/config'
import {
    GeoIPService,
    GeoIp,
    MMDB_LOAD_TIMEOUT_MS,
    MmdbLoadTimeoutError,
    MmdbMode,
    geoipServerDefaultMode,
    resolveMmdbMode,
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

        it.each<{ mode: MmdbMode }>([{ mode: 'required' }, { mode: 'optional' }])(
            'should load the mmdb when the mode is $mode',
            async ({ mode }) => {
                commonCheck(await new GeoIPService(config.MMDB_FILE_LOCATION, mode).get())
            }
        )

        it('should fail the initial load if the MMDB is required and missing', async () => {
            service = new GeoIPService('non-existent-file.mmdb', 'required')
            await expect(service.get()).rejects.toThrow(
                'GeoIP is required (MMDB_ENABLED), but the MMDB could not be loaded from non-existent-file.mmdb'
            )
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

    describe('mode', () => {
        it.each<{ mmdbEnabled: string; serverDefault: MmdbMode; expected: MmdbMode }>([
            { mmdbEnabled: '', serverDefault: 'required', expected: 'required' },
            { mmdbEnabled: ' ', serverDefault: 'disabled', expected: 'disabled' },
            { mmdbEnabled: 'true', serverDefault: 'disabled', expected: 'required' },
            { mmdbEnabled: '1', serverDefault: 'optional', expected: 'required' },
            { mmdbEnabled: 'false', serverDefault: 'required', expected: 'disabled' },
            { mmdbEnabled: 'off', serverDefault: 'optional', expected: 'disabled' },
        ])(
            'resolves MMDB_ENABLED="$mmdbEnabled" with default $serverDefault to $expected',
            ({ mmdbEnabled, serverDefault, expected }) => {
                expect(resolveMmdbMode(mmdbEnabled, serverDefault)).toBe(expected)
            }
        )

        it('rejects an MMDB_ENABLED value that is not a boolean', () => {
            expect(() => resolveMmdbMode('ture', 'optional')).toThrow(
                "MMDB_ENABLED must be true, false or empty, got 'ture'"
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
