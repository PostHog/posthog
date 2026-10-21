import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { KinesisAuthMode, awsKinesisSetupModalLogic } from './awsKinesisSetupModalLogic'

describe('awsKinesisSetupModalLogic', () => {
    let logic: ReturnType<typeof awsKinesisSetupModalLogic.build>
    let createdBodies: unknown[]

    beforeEach(() => {
        createdBodies = []
        useMocks({
            get: {
                '/api/projects/:team_id/integrations/': () => [200, { results: [] }],
            },
            post: {
                '/api/projects/:team_id/integrations/': async ({ request }) => {
                    createdBodies.push(await request.json())
                    return [201, { id: 42, kind: 'aws-kinesis', config: {} }]
                },
            },
        })
        initKeaTests()
        logic = awsKinesisSetupModalLogic({ isOpen: true, onComplete: jest.fn() })
        logic.mount()
    })

    it.each<[string, KinesisAuthMode, Record<string, string>, Record<string, string>]>([
        [
            'role',
            'role',
            { awsRoleArn: 'arn:aws:iam::123456789012:role/posthog-kinesis' },
            { aws_role_arn: 'arn:aws:iam::123456789012:role/posthog-kinesis' },
        ],
        [
            'access key',
            'access_key',
            { awsAccessKeyId: 'AKIAIOSFODNN7EXAMPLE', awsSecretAccessKey: 'example-secret' },
            { aws_access_key_id: 'AKIAIOSFODNN7EXAMPLE', aws_secret_access_key: 'example-secret' },
        ],
    ])('creates an aws-kinesis connection with only the %s fields', async (_label, authMode, formValues, config) => {
        await expectLogic(logic, () => {
            logic.actions.setAuthMode(authMode)
            logic.actions.setAwsKinesisIntegrationValues({ name: 'my stream', ...formValues })
            logic.actions.submitAwsKinesisIntegration()
        }).toFinishAllListeners()

        expect(createdBodies).toEqual([{ kind: 'aws-kinesis', config: { name: 'my stream', ...config } }])
    })
})
