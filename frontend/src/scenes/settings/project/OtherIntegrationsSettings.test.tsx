import '@testing-library/jest-dom'

import { act, cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { GitLabIntegration } from 'scenes/integrations/components/Integrations'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { mockIntegration } from '~/test/mocks'

import { OtherIntegrationsSettings } from './OtherIntegrationsSettings'

describe('GitLab connection settings', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/integrations': {
                    results: [
                        { ...mockIntegration, kind: 'gitlab', display_name: 'Example GitLab project', config: {} },
                    ],
                },
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
        jest.restoreAllMocks()
    })

    it.each([undefined, 'settings'] as const)(
        'opens setup and reports a click only when a surface is supplied (%s)',
        async (connectSurface) => {
            const capture = jest.spyOn(posthog, 'capture')
            render(
                <Provider>
                    <GitLabIntegration connectSurface={connectSurface} />
                </Provider>
            )

            await userEvent.click(screen.getByText('Connect project'))

            expect(await screen.findByText('Configure GitLab integration')).toBeInTheDocument()
            const clicks = capture.mock.calls.filter(([event]) => event === 'integration_connect_clicked')
            expect(clicks).toHaveLength(connectSurface ? 1 : 0)
            if (connectSurface) {
                expect(clicks[0][1]).toEqual({ integration: 'gitlab', integration_kind: 'gitlab', surface: 'settings' })
            }
        }
    )

    it.each([false, true])(
        'shows existing GitLab connections in Other integrations only with the flag off (%s)',
        async (enabled) => {
            featureFlagLogic.mount()
            act(() =>
                featureFlagLogic.actions.setFeatureFlags(enabled ? [FEATURE_FLAGS.WEB_GITLAB_INTEGRATION] : [], {
                    [FEATURE_FLAGS.WEB_GITLAB_INTEGRATION]: enabled,
                })
            )
            render(
                <Provider>
                    <OtherIntegrationsSettings />
                </Provider>
            )

            if (enabled) {
                expect(await screen.findByText('No other integrations connected')).toBeInTheDocument()
                expect(screen.queryByText('Example GitLab project')).not.toBeInTheDocument()
            } else {
                expect(await screen.findByText('Example GitLab project')).toBeInTheDocument()
                expect(screen.getByText('Disconnect')).toBeInTheDocument()
            }
        }
    )
})
