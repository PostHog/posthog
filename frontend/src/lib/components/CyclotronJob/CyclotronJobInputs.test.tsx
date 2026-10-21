import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { Provider } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { CyclotronJobInputs } from './CyclotronJobInputs'

const KINESIS_CONFIGURATION = {
    inputs_schema: [
        { key: 'aws_connection', type: 'integration' as const, integration: 'aws-kinesis', label: 'AWS connection' },
        { key: 'aws_access_key_id', type: 'string' as const, label: 'AWS Access Key ID', secret: true },
    ],
    inputs: {},
}

describe('CyclotronJobInputs', () => {
    afterEach(() => {
        cleanup()
    })

    it.each([
        ['shows', true],
        ['hides', false],
    ])('%s the AWS Kinesis connection input when the IAM role flag is %p', async (_name, flagEnabled) => {
        useMocks({
            get: {
                '/api/projects/:team_id/integrations': () => [200, { results: [] }],
            },
        })
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.CDP_AWS_KINESIS_IAM_ROLE]: flagEnabled })

        render(
            <Provider>
                <CyclotronJobInputs
                    configuration={KINESIS_CONFIGURATION}
                    showSource={false}
                    sampleGlobalsWithInputs={null}
                />
            </Provider>
        )

        await waitFor(() => {
            expect(screen.getByText('AWS Access Key ID')).toBeInTheDocument()
        })
        expect(screen.queryByText('AWS connection')).toEqual(flagEnabled ? expect.anything() : null)
    })
})
