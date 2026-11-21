import { Meta, StoryObj } from '@storybook/react'
import { waitFor } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import EXPERIMENT_WITH_FUNNEL_METRIC from '~/mocks/fixtures/api/experiments/experiment_with_funnel_metric.json'
import EXPERIMENT_WITH_MEAN_METRIC from '~/mocks/fixtures/api/experiments/experiment_with_mean_metric.json'
import EXPOSURE_QUERY_RESULT from '~/mocks/fixtures/api/experiments/exposure_query_result.json'
import FUNNELS_METRIC_RESULT from '~/mocks/fixtures/api/experiments/funnel_metric_result.json'
import MEAN_METRIC_RESULT from '~/mocks/fixtures/api/experiments/mean_metric_result.json'
import { NodeKind } from '~/queries/schema/schema-general'

import { recalculationMocks, resultsByMetricType } from './recalculationMocks'

// The three-dot menu each variant row offers. Its recordings submenu is the feature: it names the populations
// the Recordings tab can open for this metric, and a funnel names different ones from a mean metric.
const MAIN_BUTTON = '[data-attr="experiment-variant-actions"]'

const FUNNEL_RECALCULATION = recalculationMocks(
    EXPERIMENT_WITH_FUNNEL_METRIC,
    resultsByMetricType(EXPERIMENT_WITH_FUNNEL_METRIC, { funnel: FUNNELS_METRIC_RESULT })
)
const MEAN_RECALCULATION = recalculationMocks(
    EXPERIMENT_WITH_MEAN_METRIC,
    resultsByMetricType(EXPERIMENT_WITH_MEAN_METRIC, { mean: MEAN_METRIC_RESULT })
)

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Experiments',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2025-01-27',
        pageUrl: urls.experiment(EXPERIMENT_WITH_FUNNEL_METRIC.id),
        testOptions: { waitForSelector: MAIN_BUTTON },
        featureFlags: [FEATURE_FLAGS.EXPERIMENTS_RESULTS_REDESIGN],
    },
    decorators: [
        mswDecorator({
            get: {
                ...FUNNEL_RECALCULATION.get,
                ...MEAN_RECALCULATION.get,
                [`/api/projects/:team_id/experiments/${EXPERIMENT_WITH_FUNNEL_METRIC.id}/`]:
                    EXPERIMENT_WITH_FUNNEL_METRIC,
                [`/api/projects/:team_id/experiments/${EXPERIMENT_WITH_MEAN_METRIC.id}/`]: EXPERIMENT_WITH_MEAN_METRIC,
                '/api/projects/:team_id/experiment_holdouts': [],
                '/api/projects/:team_id/experiment_saved_metrics/': [],
                [`/api/projects/:team_id/feature_flags/${EXPERIMENT_WITH_FUNNEL_METRIC.feature_flag.id}/`]: {},
                [`/api/projects/:team_id/feature_flags/${EXPERIMENT_WITH_FUNNEL_METRIC.feature_flag.id}/status/`]: {},
                [`/api/projects/:team_id/feature_flags/${EXPERIMENT_WITH_MEAN_METRIC.feature_flag.id}/`]: {},
                [`/api/projects/:team_id/feature_flags/${EXPERIMENT_WITH_MEAN_METRIC.feature_flag.id}/status/`]: {},
                '/api/environments/:team_id/default_release_conditions/': [],
                '/api/environments/:team_id/experiments_config/': {},
                // The linkability check decides whether the menu items are offered or disabled, so
                // it is answered here rather than left to fail open on a missing handler.
                '/api/projects/:team_id/property_definitions/seen_together': {},
                // Answered so the scene does not raise a failure toast over the table.
                '/api/projects/:team_id/experiments/:id/running_time_target/': {},
            },
            post: {
                ...FUNNEL_RECALCULATION.post,
                ...MEAN_RECALCULATION.post,
                // Exposures still load through experimentLogic; metric results come from the recalculation run.
                '/api/environments/:team_id/query/:kind': async ({ request }) => {
                    const body = (await request.json()) as Record<string, any>
                    return body.query.kind === NodeKind.ExperimentExposureQuery ? [200, EXPOSURE_QUERY_RESULT] : [404]
                },
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

const meanMetricDecorator = mswDecorator({
    post: {
        // Exposures still load through experimentLogic; metric results come from the recalculation run.
        '/api/environments/:team_id/query/:kind': async ({ request }) => {
            const body = (await request.json()) as Record<string, any>
            return body.query.kind === NodeKind.ExperimentExposureQuery ? [200, EXPOSURE_QUERY_RESULT] : [404]
        },
    },
})

/**
 * Opens the first row's menu, then its recordings submenu. Storybook leaves testing-library's test id
 * attribute at its default, unlike jest and Playwright, so a `data-attr` has to be matched as a plain
 * attribute. The menu renders in a portal, so the submenu item is looked up on the document.
 */
const openFirstRowMenu: Story['play'] = async ({ canvasElement }) => {
    const menuButton = await waitFor(() => {
        const button = canvasElement.querySelector<HTMLElement>(MAIN_BUTTON)
        if (!button) {
            throw new Error('variant menu not yet rendered')
        }
        return button
    })
    await userEvent.click(menuButton)
    const recordings = await waitFor(() => {
        const item = document.querySelector<HTMLElement>('[data-attr="experiment-variant-menu-recordings"]')
        if (!item) {
            throw new Error('recordings item not yet rendered')
        }
        return item
    })
    await userEvent.click(recordings)
}

/** The table at rest: each variant row carries its menu next to the variant name. */
export const ExperimentVariantActionsMenuFunnel: Story = {}

/** A funnel's recordings submenu: the two halves of the funnel, then every recording of the variant. */
export const ExperimentVariantActionsMenuFunnelMenu: Story = {
    play: openFirstRowMenu,
}

/** A mean metric's recordings submenu names the event a session has to have fired. */
export const ExperimentVariantActionsMenuMeanMenu: Story = {
    parameters: { pageUrl: urls.experiment(EXPERIMENT_WITH_MEAN_METRIC.id) },
    decorators: [meanMetricDecorator],
    play: openFirstRowMenu,
}

/**
 * A metric the Recordings tab can't select: the submenu still opens every recording of the variant,
 * while the two modes that name the metric's population stay refused. The submenu is open because
 * the menu button looks the same either way, so this is the only state a screenshot separates.
 */
export const ExperimentVariantActionsMenuUnselectableMetric: Story = {
    parameters: { pageUrl: urls.experiment(EXPERIMENT_WITH_MEAN_METRIC.id) },
    decorators: [
        meanMetricDecorator,
        mswDecorator({
            // The metric's only event has never been seen with a session id, which is what makes it
            // unselectable on the tab.
            get: { '/api/projects/:team_id/property_definitions/seen_together': { $pageview: false } },
        }),
    ],
    play: openFirstRowMenu,
}

/**
 * The ~520px of scene a nav sidebar and an open side panel leave, where the variant menu has to stay
 * next to the variant name rather than be pushed out of reach.
 */
export const ExperimentVariantActionsMenuNarrow: Story = {
    parameters: {
        testOptions: {
            waitForSelector: MAIN_BUTTON,
            viewport: { width: 767, height: 1200 },
        },
    },
}
