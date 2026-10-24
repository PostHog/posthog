import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { Provider } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { CyclotronJobInputs } from './CyclotronJobInputs'

const KINESIS_CONNECTION = {
    id: 1,
    kind: 'aws-kinesis',
    display_name: 'Stream writer',
    icon_url: '',
    config: {},
    created_by: null,
    created_at: '2026-01-01T00:00:00Z',
}

const kinesisConfiguration = (connectionRequired: boolean): Record<string, any> => ({
    inputs_schema: [
        {
            key: 'aws_connection',
            type: 'integration' as const,
            integration: 'aws-kinesis',
            label: 'AWS connection',
            required: connectionRequired,
        },
        { key: 'aws_access_key_id', type: 'string' as const, label: 'AWS Access Key ID', secret: true },
    ],
    inputs: {},
})

describe('CyclotronJobInputs', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/integrations': () => [200, { results: [KINESIS_CONNECTION] }],
            },
        })
    })

    const renderInputs = (flagEnabled: boolean, connectionRequired = false): jest.Mock => {
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.CDP_AWS_KINESIS_IAM_ROLE]: flagEnabled })
        const onInputChange = jest.fn()

        render(
            <Provider>
                <CyclotronJobInputs
                    configuration={kinesisConfiguration(connectionRequired)}
                    onInputChange={onInputChange}
                    showSource={false}
                    sampleGlobalsWithInputs={null}
                />
            </Provider>
        )
        return onInputChange
    }

    afterEach(() => {
        cleanup()
    })

    it.each([
        ['shows', true],
        ['hides', false],
    ])('%s the AWS Kinesis connection input when the IAM role flag is %p', async (_name, flagEnabled) => {
        renderInputs(flagEnabled)

        await waitFor(() => {
            expect(screen.getByText('AWS Access Key ID')).toBeInTheDocument()
        })
        expect(screen.queryByText('AWS connection')).toEqual(flagEnabled ? expect.anything() : null)
    })

    // A Kinesis destination that signs with access keys switches to the connection when it is saved with one.
    it.each([
        ['leaves an optional connection empty', false, 0],
        ['fills a required connection', true, 1],
    ])('%s when the team has a connection', async (_name, connectionRequired, expectedCalls) => {
        const onInputChange = renderInputs(true, connectionRequired)

        await waitFor(() => {
            expect(integrationsLogic.values.integrations).toHaveLength(1)
        })
        await waitFor(() => {
            expect(onInputChange).toHaveBeenCalledTimes(expectedCalls)
        })
    })
})
