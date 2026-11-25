import { Storage } from '@google-cloud/storage'

import { getMeta, resetMeta } from '../../test-utils'
import { setupPlugin } from './index'

jest.mock('@google-cloud/storage', () => ({
    Storage: jest.fn().mockImplementation(() => ({ bucket: jest.fn() })),
}))

describe('posthog-gcs', () => {
    const serviceAccountKey = {
        type: 'service_account',
        project_id: 'my-project',
        private_key: 'PRIVATE_KEY',
        client_email: 'exporter@my-project.iam.gserviceaccount.com',
        token_uri: 'https://example.com/token',
    }

    const metaWithKey = (key: Record<string, unknown>): void => {
        resetMeta({
            config: { bucketName: 'events' },
            attachments: { googleCloudKeyJson: { contents: Buffer.from(JSON.stringify(key)) } },
        })
    }

    beforeEach(() => {
        jest.mocked(Storage).mockClear()
    })

    test('setupPlugin builds the client from only the service account email and key', async () => {
        metaWithKey(serviceAccountKey)

        await setupPlugin(getMeta())

        expect(Storage).toHaveBeenCalledWith({
            projectId: 'my-project',
            credentials: {
                client_email: 'exporter@my-project.iam.gserviceaccount.com',
                private_key: 'PRIVATE_KEY',
            },
            autoRetry: false,
        })
    })

    test.each(['external_account', 'authorized_user', undefined])('setupPlugin rejects a %s key', async (type) => {
        metaWithKey({ ...serviceAccountKey, type })

        await expect(setupPlugin(getMeta())).rejects.toThrow('must be for a service account')
        expect(Storage).not.toHaveBeenCalled()
    })
})
