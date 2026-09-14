import { Meta, StoryObj } from '@storybook/react'
import { waitFor } from '@testing-library/dom'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import featureFlags from './__mocks__/feature_flags.json'
import { featureFlagLogic } from './featureFlagLogic'

const STALE_FLAG_ID = 1498

const meta: Meta = {
    component: App,
    tags: ['ff'],
    title: 'Scenes-App/Feature Flags',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-01-28', // To stabilize relative dates
        pageUrl: urls.featureFlags(),
        testOptions: { viewport: { width: 1300, height: 2000 } },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/integrations': {},

                '/api/projects/:team_id/feature_flags': featureFlags,
                '/api/projects/:team_id/feature_flags/1111111111111/': [
                    404,
                    {
                        type: 'invalid',
                        code: 'not_found',
                        detail: 'Not found.',
                    },
                ],
                '/api/projects/:team_id/feature_flags/:flagId/': ({ params }) => {
                    const flag = featureFlags.results.find((r) => r.id === Number(params['flagId']))
                    if (flag?.id !== STALE_FLAG_ID) {
                        return [200, flag]
                    }
                    // A flag that stopped being called but still gates 40% of users. That is the
                    // case the stale banner exists for, because "stale" reads most easily as "safe
                    // to delete" when the flag is still live for real users.
                    return [
                        200,
                        {
                            ...flag,
                            last_called_at: '2022-12-14T00:00:00Z',
                            filters: { ...flag.filters, groups: [{ properties: [], rollout_percentage: 40 }] },
                        },
                    ]
                },
                '/api/projects/:team_id/feature_flags/:flagId/status': ({ params }) =>
                    Number(params['flagId']) === STALE_FLAG_ID
                        ? [
                              200,
                              {
                                  status: 'stale',
                                  reason: 'Flag has not been called in 45 days',
                                  rollout: {
                                      effectively_full_rollout: false,
                                      has_targeting_conditions: false,
                                      max_rollout_percentage: 40,
                                      is_multivariate: false,
                                  },
                              },
                          ]
                        : [
                              200,
                              {
                                  status: 'active',
                                  reason: 'Feature flag is active',
                                  rollout: {
                                      effectively_full_rollout: false,
                                      has_targeting_conditions: false,
                                      max_rollout_percentage: 50,
                                      is_multivariate: false,
                                  },
                              },
                          ],
                '/api/environments/:team_id/default_evaluation_contexts/': {
                    default_evaluation_contexts: [],
                    available_contexts: [],
                    hidden_contexts: [],
                    enabled: false,
                },
            },
            post: {
                '/api/environments/:team_id/query/:kind': {},
                // flag targeting has loaders, make sure they don't keep loading
                '/api/projects/:team_id/feature_flags/user_blast_radius/': () => [200, { affected: 120, total: 2000 }],
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>
export const FeatureFlagsList: Story = {}

export const NewFeatureFlag: Story = {
    parameters: {
        pageUrl: urls.featureFlag('new'),
    },
}

export const EditFeatureFlag: Story = {
    parameters: {
        pageUrl: urls.featureFlag(1779),
    },
}

export const EditMultiVariateFeatureFlag: Story = {
    parameters: {
        pageUrl: urls.featureFlag(1502),
    },
}

export const EditRemoteConfigFeatureFlag: Story = {
    parameters: {
        pageUrl: urls.featureFlag(1738),
    },
}

export const EditEncryptedRemoteConfigFeatureFlag: Story = {
    parameters: {
        pageUrl: urls.featureFlag(1739),
    },
}

export const StaleFeatureFlag: Story = {
    parameters: {
        pageUrl: urls.featureFlag(STALE_FLAG_ID),
    },
}

export const FeatureFlagNotFound: Story = {
    parameters: {
        pageUrl: urls.featureFlag(1111111111111),
    },
}

const waitForMountedFeatureFlagLogic = async (): Promise<ReturnType<typeof featureFlagLogic.build>> => {
    return waitFor(
        () => {
            const logic = featureFlagLogic.findMounted({ id: 'new' })
            if (!logic) {
                throw new Error('featureFlagLogic({ id: "new" }) not yet mounted')
            }
            // The new-flag loader awaits default release conditions, so wait for it to settle —
            // otherwise loadFeatureFlagSuccess resets the flag to NEW_FLAG after a play function
            // configures it below.
            if (logic.values.featureFlagLoading) {
                throw new Error('feature flag loader still pending')
            }
            return logic
        },
        { timeout: 5000 }
    )
}

const waitForErrorText = async (canvasElement: HTMLElement, expectedText: string): Promise<void> => {
    await waitFor(
        () => {
            const errors = Array.from(canvasElement.querySelectorAll('.Field--error'))
            const match = errors.some((el) => el.textContent?.includes(expectedText))
            if (!match) {
                const seen = errors.map((el) => el.textContent?.trim()).join(' | ') || '(no .Field--error elements)'
                throw new Error(`Expected error "${expectedText}" not visible. Found: ${seen}`)
            }
        },
        { timeout: 5000 }
    )
}

// These stories drive the form into a known validation-failure state via the logic so visual
// snapshots reliably capture the rendered error UI, instead of relying on brittle UI clicks.

export const NewMultivariateFlagVariantKeyError: Story = {
    parameters: {
        pageUrl: urls.featureFlag('new'),
        testOptions: { waitForLoadersToDisappear: false },
    },
    play: async ({ canvasElement }) => {
        const logic = await waitForMountedFeatureFlagLogic()

        // Set filters.multivariate directly with three variants — the third has an empty key so
        // validation will fail. Going via setFeatureFlagValue('filters', …) avoids racing with
        // the setMultivariateEnabled listener, which dispatches setMultivariateOptions in a
        // microtask and would otherwise overwrite variants added before it ran.
        logic.actions.setFeatureFlagValue('key', 'demo-flag-with-variant-error')
        logic.actions.setFeatureFlagValue('filters', {
            ...logic.values.featureFlag.filters,
            multivariate: {
                variants: [
                    { key: 'control', name: '', rollout_percentage: 50 },
                    { key: 'test', name: '', rollout_percentage: 25 },
                    { key: '', name: '', rollout_percentage: 25 },
                ],
            },
        })
        // kea-forms validators run, submitFeatureFlagFailure fires, the listener auto-expands the
        // variant panel with the empty key, and the inline error is rendered.
        logic.actions.submitFeatureFlag()

        await waitForErrorText(canvasElement, 'Please set a key')
    },
}

export const NewRemoteConfigFlagPayloadError: Story = {
    parameters: {
        pageUrl: urls.featureFlag('new'),
        testOptions: { waitForLoadersToDisappear: false },
    },
    play: async ({ canvasElement }) => {
        const logic = await waitForMountedFeatureFlagLogic()

        logic.actions.setFeatureFlagValue('key', 'demo-remote-config-flag')
        logic.actions.setFeatureFlagValue('is_remote_configuration', true)
        // Submit with empty payload: validatePayloadRequired fails, submitFeatureFlagFailure fires,
        // the listener expands the payload section, and the inline error is rendered.
        logic.actions.submitFeatureFlag()

        await waitForErrorText(canvasElement, 'Payload is required')
    },
}
