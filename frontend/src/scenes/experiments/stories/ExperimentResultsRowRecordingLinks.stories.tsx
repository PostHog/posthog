import { Meta, StoryObj } from '@storybook/react'
import { waitFor } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import EXPERIMENT_WITH_FUNNEL_METRIC from '~/mocks/fixtures/api/experiments/experiment_with_funnel_metric.json'
import EXPERIMENT_WITH_MEAN_METRIC from '~/mocks/fixtures/api/experiments/experiment_with_mean_metric.json'
import EXPOSURE_QUERY_RESULT from '~/mocks/fixtures/api/experiments/exposure_query_result.json'
import FUNNELS_METRIC_RESULT from '~/mocks/fixtures/api/experiments/funnel_metric_result.json'
import MEAN_METRIC_RESULT from '~/mocks/fixtures/api/experiments/mean_metric_result.json'
import { NodeKind } from '~/queries/schema/schema-general'

// The split button each variant row offers. The menu is the feature: it names the populations the
// Recordings tab can open for this metric, and a funnel names different ones from a mean metric.
const MAIN_BUTTON = '[data-attr="experiment-metrics-view-recordings"]'

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Experiments',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2025-01-27',
        pageUrl: urls.experiment(EXPERIMENT_WITH_FUNNEL_METRIC.id),
        testOptions: { waitForSelector: MAIN_BUTTON },
    },
    decorators: [
        mswDecorator({
            get: {
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
            },
            post: {
                // Answered so the scene does not raise a failure toast over the table.
                '/api/projects/:team_id/experiments/calculate_running_time/': {},
                '/api/environments/:team_id/query/:kind': async ({ request }) => {
                    const body = (await request.json()) as Record<string, any>

                    if (body.query.kind === NodeKind.ExperimentExposureQuery) {
                        return [200, EXPOSURE_QUERY_RESULT]
                    }

                    return [200, FUNNELS_METRIC_RESULT]
                },
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

const meanMetricDecorator = mswDecorator({
    post: {
        '/api/environments/:team_id/query/:kind': async ({ request }) => {
            const body = (await request.json()) as Record<string, any>

            if (body.query.kind === NodeKind.ExperimentExposureQuery) {
                return [200, EXPOSURE_QUERY_RESULT]
            }

            return [200, MEAN_METRIC_RESULT]
        },
    },
})

/**
 * Opens the first row's menu. Storybook leaves testing-library's test id attribute at its default,
 * unlike jest and Playwright, so a `data-attr` has to be matched as a plain attribute.
 */
const openFirstRowMenu: Story['play'] = async ({ canvasElement }) => {
    const caret = await waitFor(() => {
        const button = canvasElement.querySelector<HTMLElement>('[data-attr="experiment-metrics-recordings-menu"]')
        if (!button) {
            throw new Error('recordings menu caret not yet rendered')
        }
        return button
    })
    await userEvent.click(caret)
}

/** The one-click path: the button names the action, not the population it opens. */
export const ExperimentResultsRowRecordingLinksFunnel: Story = {}

/** A funnel's menu: the two halves of the funnel, then every recording of the variant. */
export const ExperimentResultsRowRecordingLinksFunnelMenu: Story = {
    play: openFirstRowMenu,
}

/** A mean metric's menu names the event a session has to have fired. */
export const ExperimentResultsRowRecordingLinksMeanMenu: Story = {
    parameters: { pageUrl: urls.experiment(EXPERIMENT_WITH_MEAN_METRIC.id) },
    decorators: [meanMetricDecorator],
    play: openFirstRowMenu,
}

/**
 * A metric the Recordings tab can't select: the button stays usable and opens every recording of
 * the variant, while the two modes that name the metric's population stay refused. The menu is open
 * because the button itself looks the same either way, so this is the only state a screenshot
 * separates.
 */
export const ExperimentResultsRowRecordingLinksUnselectableMetric: Story = {
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
 * The ~520px of scene a nav sidebar and an open side panel leave, where the button has to hold its
 * column rather than push the rest of the table out of reach.
 */
export const ExperimentResultsRowRecordingLinksNarrow: Story = {
    parameters: {
        testOptions: {
            waitForSelector: MAIN_BUTTON,
            viewport: { width: 767, height: 1200 },
        },
    },
}
