import { PubSub } from '@google-cloud/pubsub'

import { getMeta, resetMeta } from '../../test-utils'
import { setupPlugin } from './index'

jest.mock('@google-cloud/pubsub', () => ({
    PubSub: jest.fn().mockImplementation(() => ({
        topic: () => ({ getMetadata: jest.fn().mockResolvedValue([{}]) }),
    })),
}))

describe('pubsub', () => {
    const serviceAccountKey = {
        type: 'service_account',
        project_id: 'my-project',
        private_key: 'PRIVATE_KEY',
        client_email: 'exporter@my-project.iam.gserviceaccount.com',
        token_uri: 'https://example.com/token',
    }

    beforeEach(() => {
        jest.mocked(PubSub).mockClear()
    })

    test('setupPlugin builds the client from only the service account email and key', async () => {
        resetMeta({ config: { topicId: 'events', googleCloudKeyJson: serviceAccountKey } })

        await setupPlugin(getMeta())

        expect(PubSub).toHaveBeenCalledWith({
            projectId: 'my-project',
            credentials: {
                client_email: 'exporter@my-project.iam.gserviceaccount.com',
                private_key: 'PRIVATE_KEY',
            },
        })
    })

    test.each(['external_account', 'authorized_user', undefined])('setupPlugin rejects a %s key', async (type) => {
        resetMeta({ config: { topicId: 'events', googleCloudKeyJson: { ...serviceAccountKey, type } } })

        await expect(setupPlugin(getMeta())).rejects.toThrow('must be for a service account')
        expect(PubSub).not.toHaveBeenCalled()
    })
})
