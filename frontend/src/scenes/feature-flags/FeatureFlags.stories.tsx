import { Meta, StoryObj } from '@storybook/react'
import { waitFor } from '@testing-library/dom'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { toPaginatedResponse } from '~/mocks/handlers'

import featureFlags from './__mocks__/feature_flags.json'
import { featureFlagLogic } from './featureFlagLogic'

const STALE_FLAG_ID = 1498
const RULES_V2_FLAG_ID = 1802
const DELETED_FLAG_ID = 1526

const SPLIT_RULE_FIELDS = {
    rule_type: 'experiment',
    targeting: { properties: [] },
    experiment_id: null,
    assignment_algorithm: 'sha1_60_v1',
    assign_by: 'person',
}

// Served on its own route only, so the list stories keep their rows.
const RULES_V2_SPLIT_FLAG = {
    ...featureFlags.results.find((flag) => flag.id === RULES_V2_FLAG_ID),
    id: 1803,
    key: 'checkout-layout-rules-v2',
    name: 'Checkout layout, split across three variants',
    filters: {
        version: 2,
        return_type: 'string',
        default_value: 'standard',
        rules: [
            {
                id: '2b7e9c41-5d3a-4f8e-b6a1-9c0d2e3f4a5b',
                rule_type: 'targeted_release',
                description: 'Internal testers',
                targeting: {
                    properties: [{ key: 'email', type: 'person', value: '@hedgehog.example', operator: 'icontains' }],
                },
                value: 'compact',
            },
            {
                ...SPLIT_RULE_FIELDS,
                id: '7c1f2e3d-4b5a-4c6d-8e9f-0a1b2c3d4e5f',
                description: 'Layout test',
                paused: false,
                rollout_percentage: 50,
                on_rollout_miss: 'continue',
                seed: '3e8f1a2b-9c4d-4e5f-a6b7-c8d9e0f1a2b3',
                variants: [
                    { key: 'control', weight: 33.34, value: 'standard' },
                    { key: 'compact', weight: 33.33, value: 'compact' },
                    { key: 'spacious', weight: 33.33, value: 'spacious' },
                ],
                holdout: { id: null, seed: '5a6b7c8d-9e0f-4a1b-8c2d-3e4f5a6b7c8d', exclusion_percentage: 5 },
            },
            {
                ...SPLIT_RULE_FIELDS,
                id: '9d8c7b6a-5f4e-4d3c-9b2a-1f0e9d8c7b6a',
                description: 'Mobile layout test, paused',
                paused: true,
                rollout_percentage: 100,
                on_rollout_miss: 'return_default',
                seed: '0f1e2d3c-4b5a-4968-8776-655443322110',
                variants: [
                    { key: 'control', weight: 50, value: 'standard' },
                    { key: 'stacked', weight: 50, value: 'stacked' },
                ],
            },
        ],
    },
}

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
        featureFlags: [FEATURE_FLAGS.REALTIME_COHORT_FLAG_TARGETING],
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/integrations': {},
                '/api/projects/:team_id/cohorts/': toPaginatedResponse([
                    {
                        id: 1,
                        name: 'Viewed pricing this week',
                        count: 4321,
                        is_static: false,
                        filters: { properties: { type: 'AND', values: [] } },
                        realtime: { state: 'ready', ready_at: '2023-01-27T09:40:00Z', build: null },
                    },
                ]),

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
                    if (Number(params['flagId']) === RULES_V2_SPLIT_FLAG.id) {
                        return [200, RULES_V2_SPLIT_FLAG]
                    }
                    const flag = featureFlags.results.find((r) => r.id === Number(params['flagId']))
                    if (flag?.id === DELETED_FLAG_ID) {
                        return [200, { ...flag, deleted: true, can_edit: true }]
                    }
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

export const EditFeatureFlagConditionsWithRealtimeCohort: Story = {
    parameters: {
        pageUrl: `${urls.featureFlag(1779)}?edit=true`,
        testOptions: { waitForLoadersToDisappear: false },
    },
    play: async ({ canvasElement }) => {
        // Condition sets start collapsed, and the realtime tag sits on the expanded cohort row.
        const expandAll = await waitFor(
            () => {
                const button = canvasElement.querySelector<HTMLButtonElement>('[data-attr="expand-all-conditions"]')
                if (!button) {
                    throw new Error('release conditions for flag 1779 not yet rendered')
                }
                return button
            },
            // The flag scene is a lazy chunk, so give a cold bundle time to arrive.
            { timeout: 30000 }
        )
        expandAll.click()
        await waitFor(
            () => {
                if (!canvasElement.querySelector('[data-attr="collapse-all-conditions"]')) {
                    throw new Error('condition sets not expanded yet')
                }
            },
            { timeout: 5000 }
        )
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

export const FeatureFlagsListWithRulesV2Flag: Story = {
    parameters: {
        pageUrl: `${urls.featureFlags()}?search=rules-v2`,
    },
}

export const RulesV2FeatureFlag: Story = {
    parameters: {
        pageUrl: urls.featureFlag(RULES_V2_FLAG_ID),
    },
}

// Without the editor flag, `?edit=true` must still show the read-only view, because the v1 form's full save would
// rewrite the document.
export const RulesV2FeatureFlagEditDeepLink: Story = {
    parameters: {
        pageUrl: `${urls.featureFlag(RULES_V2_FLAG_ID)}?edit=true`,
    },
}

export const NewRulesV2FeatureFlag: Story = {
    parameters: {
        pageUrl: urls.featureFlagNew({ format: 'rules_v2' }),
        featureFlags: [FEATURE_FLAGS.REALTIME_COHORT_FLAG_TARGETING, FEATURE_FLAGS.FEATURE_FLAG_RULES_V2_EDITOR],
    },
}

export const EditRulesV2FeatureFlag: Story = {
    parameters: {
        pageUrl: `${urls.featureFlag(RULES_V2_FLAG_ID)}?edit=true`,
        featureFlags: [FEATURE_FLAGS.REALTIME_COHORT_FLAG_TARGETING, FEATURE_FLAGS.FEATURE_FLAG_RULES_V2_EDITOR],
    },
}

export const RulesV2FeatureFlagWithVariantSplit: Story = {
    parameters: {
        pageUrl: urls.featureFlag(RULES_V2_SPLIT_FLAG.id),
    },
}

export const EditRulesV2FeatureFlagWithVariantSplit: Story = {
    parameters: {
        pageUrl: `${urls.featureFlag(RULES_V2_SPLIT_FLAG.id)}?edit=true`,
        featureFlags: [FEATURE_FLAGS.REALTIME_COHORT_FLAG_TARGETING, FEATURE_FLAGS.FEATURE_FLAG_RULES_V2_EDITOR],
    },
}

export const StaleFeatureFlagWithAiAssessment: Story = {
    parameters: {
        pageUrl: urls.featureFlag(STALE_FLAG_ID),
        featureFlags: [
            FEATURE_FLAGS.REALTIME_COHORT_FLAG_TARGETING,
            FEATURE_FLAGS.PHAI_SANDBOX_MODE,
            FEATURE_FLAGS.FEATURE_FLAG_CLEANUP_ASSESSMENT,
        ],
    },
    play: async ({ canvasElement }) => {
        await waitFor(
            () => {
                if (!canvasElement.querySelector('[data-attr="feature-flag-stale-banner-review-cleanup"]')) {
                    throw new Error('AI assessment action not rendered')
                }
            },
            { timeout: 30000 }
        )
    },
}

export const DeletedFeatureFlag: Story = {
    parameters: {
        pageUrl: urls.featureFlag(DELETED_FLAG_ID),
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
