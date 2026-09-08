import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { CyclotronJobInputs } from '../CyclotronJobInputs'

const slackIntegration = (scope: string): Record<string, any> => ({
    id: 1,
    kind: 'slack',
    display_name: 'PostHog HQ',
    icon_url: '',
    config: { scope },
    created_by: null,
    created_at: '2026-01-01T00:00:00Z',
})

const CONFIGURATION = {
    inputs_schema: [
        { key: 'slack_workspace', type: 'integration' as const, integration: 'slack', label: 'Slack workspace' },
        {
            key: 'icon_emoji',
            type: 'string' as const,
            label: 'Emoji icon',
            integration_key: 'slack_workspace',
            requiredScopes: 'chat:write.customize',
        },
    ],
    inputs: { slack_workspace: { value: 1 }, icon_emoji: { value: ':hedgehog:' } },
}

describe('MissingScopesHint', () => {
    afterEach(() => {
        cleanup()
    })

    // A workspace connected before chat:write.customize was requested still posts messages, so the
    // customization fields must say what they need rather than the whole connection erroring.
    it.each([
        ['the connection lacks the scope', 'chat:write', true],
        ['the connection granted the scope', 'chat:write chat:write.customize', false],
    ])('given %s', async (_name, scope, expectHint) => {
        useMocks({
            get: {
                '/api/environments/:team_id/integrations': () => [200, { results: [slackIntegration(scope)] }],
            },
        })
        initKeaTests()

        render(
            <Provider>
                <CyclotronJobInputs configuration={CONFIGURATION} showSource={false} sampleGlobalsWithInputs={null} />
            </Provider>
        )

        await waitFor(() => {
            expect(screen.getByText('Emoji icon')).toBeInTheDocument()
        })
        await waitFor(() => {
            expect(screen.queryByText('chat:write.customize')).toEqual(expectHint ? expect.anything() : null)
        })
    })

    // The hint subscribes to every integration on the team. A form with no scope-carrying input must
    // not mount that subscription, or a plain webhook config would load integrations it never uses.
    it('does not load integrations for a form without scope-carrying inputs', async () => {
        let loads = 0
        useMocks({
            get: {
                '/api/environments/:team_id/integrations': () => {
                    loads += 1
                    return [200, { results: [] }]
                },
            },
        })
        initKeaTests()

        render(
            <Provider>
                <CyclotronJobInputs
                    configuration={{
                        inputs_schema: [{ key: 'url', type: 'string', label: 'Webhook URL' }],
                        inputs: { url: { value: 'https://example.com/hook' } },
                    }}
                    showSource={false}
                    sampleGlobalsWithInputs={null}
                />
            </Provider>
        )

        await waitFor(() => {
            expect(screen.getByText('Webhook URL')).toBeInTheDocument()
        })
        expect(loads).toEqual(0)
    })
})
