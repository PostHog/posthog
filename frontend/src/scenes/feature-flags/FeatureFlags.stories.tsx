import { Meta, StoryObj } from '@storybook/react'
import { waitFor } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import featureFlags from './__mocks__/feature_flags.json'

const meta: Meta = {
    component: App,
    tags: ['ff'],
    title: 'Scenes-App/Feature Flags',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-01-28', // To stabilize relative dates
        pageUrl: urls.featureFlags(),
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
                '/api/projects/:team_id/feature_flags/:flagId/': (req) => [
                    200,
                    featureFlags.results.find((r) => r.id === Number(req.params['flagId'])),
                ],
                '/api/projects/:team_id/feature_flags/:flagId/status': () => [
                    200,
                    {
                        status: 'active',
                        reason: 'Feature flag is active',
                    },
                ],
                '/api/environments/:team_id/default_evaluation_contexts/': {
                    default_evaluation_contexts: [],
                    available_contexts: [],
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

export const FeatureFlagNotFound: Story = {
    parameters: {
        pageUrl: urls.featureFlag(1111111111111),
    },
}

const querySelector = async <T extends HTMLElement>(
    canvasElement: HTMLElement,
    selector: string,
    timeout = 4000
): Promise<T> => {
    return waitFor(
        () => {
            const el = canvasElement.querySelector<T>(selector)
            if (!el) {
                throw new Error(`Element not found: ${selector}`)
            }
            return el
        },
        { timeout }
    )
}

export const NewMultivariateFlagVariantKeyError: Story = {
    parameters: {
        pageUrl: urls.featureFlag('new'),
        testOptions: { waitForLoadersToDisappear: false },
    },
    play: async ({ canvasElement }) => {
        // Fill the top-level key so its error doesn't preempt the variant key error.
        const keyInput = await querySelector<HTMLInputElement>(canvasElement, '[data-attr="feature-flag-key"]')
        await userEvent.type(keyInput, 'demo-flag-with-variant-error')

        await userEvent.click(await querySelector(canvasElement, '[data-attr="feature-flag-type-multivariate"]'))
        // Add a third variant — it starts with an empty key, which will fail validation on submit.
        await userEvent.click(await querySelector(canvasElement, '[data-attr="feature-flag-add-variant"]'))
        await userEvent.click(await querySelector(canvasElement, '[data-attr="save-feature-flag"]'))

        // After submit fails, the listener should auto-expand the panel with the empty-key variant
        // so the error is visible. We wait for the rendered error span to appear.
        await waitFor(
            () => {
                const errorEl = canvasElement.querySelector('[data-attr="feature-flag-variant-key-2"]')
                if (!errorEl) {
                    throw new Error('Variant 2 input not visible — panel did not auto-expand')
                }
            },
            { timeout: 4000 }
        )
    },
}

export const NewRemoteConfigFlagPayloadError: Story = {
    parameters: {
        pageUrl: urls.featureFlag('new'),
        testOptions: { waitForLoadersToDisappear: false },
    },
    play: async ({ canvasElement }) => {
        const keyInput = await querySelector<HTMLInputElement>(canvasElement, '[data-attr="feature-flag-key"]')
        await userEvent.type(keyInput, 'demo-remote-config-flag')

        await userEvent.click(await querySelector(canvasElement, '[data-attr="feature-flag-type-remote_config"]'))
        await userEvent.click(await querySelector(canvasElement, '[data-attr="save-feature-flag"]'))

        // After submit fails the payload section should auto-expand and reveal the error.
        await waitFor(
            () => {
                const errorEl = canvasElement.querySelector('.Field--error')
                if (!errorEl) {
                    throw new Error('No .Field--error element rendered — payload section did not auto-expand')
                }
            },
            { timeout: 4000 }
        )
    },
}
