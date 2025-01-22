import { Hub } from '../types'
import { HogFunctionManagerService } from './services/hog-function-manager.service'

describe('HogFunctionManager', () => {
    let hub: Hub
    let manager: HogFunctionManagerService

    beforeEach(() => {
        hub = {
            mmdb: undefined, // No MMDB configured
            postgres: {
                query: jest.fn().mockResolvedValue({ rows: [] }),
                transaction: jest.fn(),
            },
            CELERY_DEFAULT_QUEUE: 'celery-default',
            PLUGINS_CELERY_QUEUE: 'plugins-celery',
            OBJECT_STORAGE_ENABLED: true,
            OBJECT_STORAGE_REGION: '',
            OBJECT_STORAGE_ENDPOINT: '',
            OBJECT_STORAGE_ACCESS_KEY_ID: '',
            OBJECT_STORAGE_SECRET_ACCESS_KEY: '',
            OBJECT_STORAGE_BUCKET: '',
            statsd: {
                timing: jest.fn(),
                increment: jest.fn(),
                gauge: jest.fn(),
                close: jest.fn(),
            },
            instanceId: 'test',
            capabilities: {},
        } as any as Hub

        manager = new HogFunctionManagerService(hub)
    })

    describe('start()', () => {
        it('should fail if transformations are enabled but MMDB is not configured', async () => {
            await expect(manager.start(['transformation'])).rejects.toThrow(
                'GeoIP transformation requires MMDB to be configured. Please ensure the MMDB file is properly set up.'
            )
        })

        it('should start successfully if MMDB is configured', async () => {
            hub.mmdb = {} as any // Mock MMDB as configured
            await expect(manager.start(['transformation'])).resolves.not.toThrow()
        })

        it('should start successfully if transformations are not enabled', async () => {
            await expect(manager.start(['destination'])).resolves.not.toThrow()
        })
    })
})
