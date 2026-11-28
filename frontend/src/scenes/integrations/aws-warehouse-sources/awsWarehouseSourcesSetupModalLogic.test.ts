import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { integrationsCreate } from 'products/integrations/frontend/generated/api'

import { awsWarehouseSourcesSetupModalLogic } from './awsWarehouseSourcesSetupModalLogic'

jest.mock('products/integrations/frontend/generated/api', () => ({
    ...jest.requireActual('products/integrations/frontend/generated/api'),
    integrationsCreate: jest.fn(),
}))

describe('awsWarehouseSourcesSetupModalLogic', () => {
    let logic: ReturnType<typeof awsWarehouseSourcesSetupModalLogic.build>
    const createSpy = jest.mocked(integrationsCreate)

    useMocks({
        get: {
            '/api/projects/:team_id/integrations/': () => [200, { results: [] }],
        },
    })

    beforeEach(() => {
        initKeaTests()
        logic = awsWarehouseSourcesSetupModalLogic({ isOpen: true, onComplete: jest.fn() })
        logic.mount()
        createSpy.mockReset().mockResolvedValue({ id: 42 } as any)
    })

    it('creates an aws-warehouse-sources connection with the role ARN', async () => {
        await expectLogic(logic, () => {
            logic.actions.setAwsWarehouseSourcesIntegrationValues({
                name: 'my connection',
                awsRoleArn: ' arn:aws:iam::123456789012:role/posthog-warehouse-sources ',
            })
            logic.actions.submitAwsWarehouseSourcesIntegration()
        }).toFinishAllListeners()

        expect(createSpy).toHaveBeenCalledWith(expect.any(String), {
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
