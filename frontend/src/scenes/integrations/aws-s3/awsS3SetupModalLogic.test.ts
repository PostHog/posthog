import { expectLogic } from 'kea-test-utils'

import apiReal from 'lib/api'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { awsS3SetupModalLogic } from './awsS3SetupModalLogic'

describe('awsS3SetupModalLogic', () => {
    let logic: ReturnType<typeof awsS3SetupModalLogic.build>
    let createSpy: jest.SpyInstance

    useMocks({
        get: {
            '/api/environments/:team_id/integrations/': () => [200, { results: [] }],
        },
    })

    beforeEach(() => {
        initKeaTests()
        logic = awsS3SetupModalLogic({ isOpen: true, onComplete: jest.fn() })
        logic.mount()
        createSpy = jest.spyOn(apiReal.integrations, 'create').mockResolvedValue({
            id: 42,
            kind: 'aws-s3',
            display_name: 'my connection',
            icon_url: '',
            config: {},
            created_at: '2026-07-13T00:00:00Z',
        } as any)
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it('sends only aws_role_arn in role mode', async () => {
        await expectLogic(logic, () => {
            logic.actions.setAwsS3IntegrationValues({
                name: 'my connection',
                awsRoleArn: 'arn:aws:iam::123456789012:role/posthog-batch-exports',
            })
            logic.actions.submitAwsS3Integration()
        }).toFinishAllListeners()

        expect(createSpy).toHaveBeenCalledWith({
            kind: 'aws-s3',
            config: {
                name: 'my connection',
                aws_role_arn: 'arn:aws:iam::123456789012:role/posthog-batch-exports',
            },
        })
    })

    it('sends only access keys in access key mode', async () => {
        await expectLogic(logic, () => {
            logic.actions.setAuthMode('access_key')
            logic.actions.setAwsS3IntegrationValues({
                name: 'my connection',
                awsAccessKeyId: 'AKIAIOSFODNN7EXAMPLE',
                awsSecretAccessKey: 'secret',
            })
            logic.actions.submitAwsS3Integration()
        }).toFinishAllListeners()

        expect(createSpy).toHaveBeenCalledWith({
            kind: 'aws-s3',
            config: {
                name: 'my connection',
                aws_access_key_id: 'AKIAIOSFODNN7EXAMPLE',
                aws_secret_access_key: 'secret',
            },
        })
    })

    it.each(['', 'not-an-arn', 'arn:aws:iam::123:role/too-short-account'])(
        'does not submit in role mode with invalid ARN %p',
        async (awsRoleArn) => {
            await expectLogic(logic, () => {
                logic.actions.setAwsS3IntegrationValues({ name: 'my connection', awsRoleArn })
                logic.actions.submitAwsS3Integration()
            }).toFinishAllListeners()

            expect(createSpy).not.toHaveBeenCalled()
        }
    )

    it('clears credential fields when switching auth mode', async () => {
        await expectLogic(logic, () => {
            logic.actions.setAwsS3IntegrationValues({
                name: 'my connection',
                awsRoleArn: 'arn:aws:iam::123456789012:role/posthog-batch-exports',
            })
            logic.actions.setAuthMode('access_key')
        }).toFinishAllListeners()

        expect(logic.values.awsS3Integration).toMatchObject({
            name: 'my connection',
            awsRoleArn: '',
            awsAccessKeyId: '',
            awsSecretAccessKey: '',
        })
    })
})
