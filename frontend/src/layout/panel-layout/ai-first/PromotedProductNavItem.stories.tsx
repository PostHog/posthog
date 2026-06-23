import { Meta, StoryObj, type Decorator } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { getAppContext } from 'lib/utils/getAppContext'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import { localStorageOverrideKey, localStorageProductKey } from './promotedProductLogic'

/**
 * The promoted-product entry lives in the left project nav, so these stories render the
 * full `App` with the navigation captured. We vary only the two inputs that decide what
 * the slot shows: the `promoted-product` flag variant and whether the team has a primary
 * onboarding product. With no product, `intent`/`intent_plus` fall back to a dashboards link.
 */
const withPromotedProductIntent =
    (intent: string | null): Decorator =>
    (Story) => {
        const ctx = getAppContext()
        const teamId = ctx?.current_team?.id
        if (teamId != null) {
            // Clear any leakage from a previous story so AppContext is the only source.
            window.localStorage.removeItem(localStorageProductKey(teamId))
            window.localStorage.removeItem(localStorageOverrideKey(teamId))
        }
        if (ctx) {
            ctx.promoted_product_intent = intent
        }
        return <Story />
    }

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Promoted Product',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        pageUrl: urls.dashboards(),
        testOptions: {
            includeNavigationInSnapshot: true,
        },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/dashboard_templates/': {},
                '/api/projects/:id/integrations': { results: [] },
                '/api/organizations/:organization_id/pipeline_destinations/': { results: [] },
                '/api/projects/:id/pipeline_destination_configs/': { results: [] },
                '/api/projects/:id/batch_exports/': { results: [] },
                '/api/projects/:id/surveys/': { results: [] },
                '/api/projects/:id/surveys/responses_count/': { results: [] },
                '/api/environments/:team_id/exports/': { results: [] },
                '/api/environments/:team_id/events': { results: [] },
            },
            post: {
                '/api/environments/:team_id/query/:kind': {},
            },
        }),
    ],
}
export default meta

type Story = StoryObj

const PROMOTED_PRODUCT = 'session_replay'

// control: the entry never renders, with or without a product.
export const ControlNoProduct: Story = {
    parameters: { featureFlags: { [FEATURE_FLAGS.PROMOTED_PRODUCT]: 'control' } },
    decorators: [withPromotedProductIntent(null)],
}

export const ControlWithProduct: Story = {
    parameters: { featureFlags: { [FEATURE_FLAGS.PROMOTED_PRODUCT]: 'control' } },
    decorators: [withPromotedProductIntent(PROMOTED_PRODUCT)],
}

// intent: renders the entry; falls back to a dashboards link when there's no product.
export const IntentNoProduct: Story = {
    parameters: { featureFlags: { [FEATURE_FLAGS.PROMOTED_PRODUCT]: 'intent' } },
    decorators: [withPromotedProductIntent(null)],
}

export const IntentWithProduct: Story = {
    parameters: { featureFlags: { [FEATURE_FLAGS.PROMOTED_PRODUCT]: 'intent' } },
    decorators: [withPromotedProductIntent(PROMOTED_PRODUCT)],
}

// intent_plus: same as intent, plus the configure cog.
export const IntentPlusNoProduct: Story = {
    parameters: { featureFlags: { [FEATURE_FLAGS.PROMOTED_PRODUCT]: 'intent_plus' } },
    decorators: [withPromotedProductIntent(null)],
}

export const IntentPlusWithProduct: Story = {
    parameters: { featureFlags: { [FEATURE_FLAGS.PROMOTED_PRODUCT]: 'intent_plus' } },
    decorators: [withPromotedProductIntent(PROMOTED_PRODUCT)],
}
