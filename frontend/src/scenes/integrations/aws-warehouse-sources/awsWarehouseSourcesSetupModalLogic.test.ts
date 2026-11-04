import { expectLogic } from 'kea-test-utils'

import apiReal from 'lib/api'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { awsWarehouseSourcesSetupModalLogic } from './awsWarehouseSourcesSetupModalLogic'

describe('awsWarehouseSourcesSetupModalLogic', () => {
    let logic: ReturnType<typeof awsWarehouseSourcesSetupModalLogic.build>
    let createSpy: jest.SpyInstance

    useMocks({
        get: {
            '/api/projects/:team_id/integrations/': () => [200, { results: [] }],
        },
    })

    beforeEach(() => {
        initKeaTests()
        logic = awsWarehouseSourcesSetupModalLogic({ isOpen: true, onComplete: jest.fn() })
        logic.mount()
        createSpy = jest.spyOn(apiReal.integrations, 'create').mockResolvedValue({ id: 42 } as any)
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it('creates an aws-warehouse-sources connection with the role ARN', async () => {
        await expectLogic(logic, () => {
            logic.actions.setAwsWarehouseSourcesIntegrationValues({
                name: 'my connection',
                awsRoleArn: ' arn:aws:iam::123456789012:role/posthog-warehouse-sources ',
            })
            logic.actions.submitAwsWarehouseSourcesIntegration()
        }).toFinishAllListeners()

        expect(createSpy).toHaveBeenCalledWith({
            kind: 'aws-warehouse-sources',
            config: {
                name: 'my connection',
                aws_role_arn: 'arn:aws:iam::123456789012:role/posthog-warehouse-sources',
            },
        })
    })

    it.each(['', 'not-an-arn', 'arn:aws:iam::123:role/too-short-account'])(
        'does not submit with invalid ARN %p',
        async (awsRoleArn) => {
            await expectLogic(logic, () => {
                logic.actions.setAwsWarehouseSourcesIntegrationValues({ name: 'my connection', awsRoleArn })
                logic.actions.submitAwsWarehouseSourcesIntegration()
            }).toFinishAllListeners()

            expect(createSpy).not.toHaveBeenCalled()
        }
    )
})
