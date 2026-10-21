import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { KinesisAuthMode, awsKinesisSetupModalLogic } from './awsKinesisSetupModalLogic'

describe('awsKinesisSetupModalLogic', () => {
    let logic: ReturnType<typeof awsKinesisSetupModalLogic.build>
    let createdBodies: unknown[]
    let createdInTeams: string[]

    beforeEach(() => {
        createdBodies = []
        createdInTeams = []
        useMocks({
            get: {
                '/api/projects/:team_id/integrations/': () => [200, { results: [] }],
            },
            post: {
                '/api/projects/:team_id/integrations/': async ({ request, params }) => {
                    createdBodies.push(await request.json())
                    createdInTeams.push(String(params.team_id))
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

    it('creates the connection in the current environment, not in its parent project', async () => {
        teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, id: MOCK_DEFAULT_TEAM.id + 1 })

        await expectLogic(logic, () => {
            logic.actions.setAwsKinesisIntegrationValues({
                name: 'my stream',
                awsRoleArn: 'arn:aws:iam::123456789012:role/posthog-kinesis',
            })
            logic.actions.submitAwsKinesisIntegration()
        }).toFinishAllListeners()

        expect(createdInTeams).toEqual([String(MOCK_DEFAULT_TEAM.id + 1)])
    })
})
