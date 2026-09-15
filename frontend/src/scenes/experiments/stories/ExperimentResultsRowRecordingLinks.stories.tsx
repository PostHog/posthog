import { Meta, StoryObj } from '@storybook/react'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import EXPERIMENT_WITH_FUNNEL_METRIC from '~/mocks/fixtures/api/experiments/experiment_with_funnel_metric.json'
import EXPERIMENT_WITH_MEAN_METRIC from '~/mocks/fixtures/api/experiments/experiment_with_mean_metric.json'
import EXPOSURE_QUERY_RESULT from '~/mocks/fixtures/api/experiments/exposure_query_result.json'
import FUNNELS_METRIC_RESULT from '~/mocks/fixtures/api/experiments/funnel_metric_result.json'
import MEAN_METRIC_RESULT from '~/mocks/fixtures/api/experiments/mean_metric_result.json'
import { NodeKind } from '~/queries/schema/schema-general'

// The pair of recordings links each variant row offers. The labels are the feature: they name the
// population the Recordings tab opens on, and a funnel names a different one from a mean metric.
const meta: Meta = {
    component: App,
    title: 'Scenes-App/Experiments',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2025-01-27',
        pageUrl: urls.experiment(EXPERIMENT_WITH_FUNNEL_METRIC.id),
        testOptions: { waitForSelector: '[data-attr="experiment-metrics-recordings-negative"]' },
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
                // The linkability check decides whether the links are offered or disabled, so it is
                // answered here rather than left to fail open on a missing handler.
                '/api/projects/:team_id/property_definitions/seen_together': {},
            },
            post: {
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

/** A funnel metric: the pair reads finished / didn't finish the funnel. */
export const ExperimentResultsRowRecordingLinksFunnel: Story = {}

/** A mean metric: the pair names the event a session has to have fired. */
export const ExperimentResultsRowRecordingLinksMean: Story = {
    parameters: { pageUrl: urls.experiment(EXPERIMENT_WITH_MEAN_METRIC.id) },
    decorators: [
        mswDecorator({
            post: {
                '/api/environments/:team_id/query/:kind': async ({ request }) => {
                    const body = (await request.json()) as Record<string, any>

                    if (body.query.kind === NodeKind.ExperimentExposureQuery) {
                        return [200, EXPOSURE_QUERY_RESULT]
                    }

                    return [200, MEAN_METRIC_RESULT]
                },
            },
        }),
    ],
}

/**
 * The scene a nav sidebar and an open side panel leave, where the two links have to wrap inside
 * their column rather than push the table sideways.
 */
export const ExperimentResultsRowRecordingLinksNarrow: Story = {
    parameters: {
        testOptions: {
            waitForSelector: '[data-attr="experiment-metrics-recordings-negative"]',
            viewport: { width: 767, height: 1200 },
        },
    },
}
