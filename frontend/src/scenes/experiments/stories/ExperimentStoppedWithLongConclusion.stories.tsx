import { Meta, StoryObj } from '@storybook/react'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import EXPERIMENT_WITH_FUNNEL_METRIC from '~/mocks/fixtures/api/experiments/experiment_with_funnel_metric.json'
import EXPOSURE_QUERY_RESULT from '~/mocks/fixtures/api/experiments/exposure_query_result.json'
import FUNNELS_METRIC_RESULT from '~/mocks/fixtures/api/experiments/funnel_metric_result.json'
import { NodeKind } from '~/queries/schema/schema-general'

const LONG_CONCLUSION_COMMENT = [
    'We shipped the test variant on qualitative feedback rather than on a measured lift.',
    'The primary metric moved by a small amount that never reached significance, and the secondary metrics disagreed with each other about the direction of the effect.',
    'The signup metric favored the variant while the activation metric favored control, which points to sampling noise rather than a real effect.',
    'The test reached its planned sample size, but that sample size only resolves large relative effects, and copy changes of this kind rarely move the metric that much.',
    'Resolving the observed gap would need several months of traffic at current volumes, which is longer than the team is willing to wait for a headline change.',
    'For the next test we plan to use a metric closer to the surface being changed, run fewer variants so each one gets more traffic, and vary the page structure rather than the wording alone.',
    'We also plan to set the horizon up front and stick to it, since the current test was monitored daily under a fixed-horizon configuration.',
    'The exposure counts were balanced across variants and the sample ratio check passed, so the assignment mechanism itself is not in question.',
    'A small share of users saw more than one variant, which is expected with anonymous bucketing on a logged-out page and biases the result toward null.',
    'The number of secondary metrics also inflated the false positive risk, since dozens of comparisons at the default threshold are expected to produce a few significant results by chance alone.',
    'Future tests on this surface should cut the secondary metric list down to the few that can plausibly move, and treat the rest as debugging context rather than decision inputs.',
    'The flag was left at its final rollout state, the release conditions were preserved, and no cleanup was performed as part of ending the experiment.',
    'Overall the test produced a useful negative result: it rules out large effects from wording changes alone and sharpens the design of the next iteration.',
].join(' ')

const EXPERIMENT_STOPPED_WITH_LONG_CONCLUSION = {
    ...EXPERIMENT_WITH_FUNNEL_METRIC,
    end_date: '2025-01-20T14:39:00Z',
    conclusion: 'stopped_early',
    conclusion_comment: LONG_CONCLUSION_COMMENT,
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Experiments',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2025-01-27',
        pageUrl: urls.experiment(EXPERIMENT_STOPPED_WITH_LONG_CONCLUSION.id),
        testOptions: {
            // The funnel chart only renders once the metric result AND the exposure query have
            // both resolved. The loader wait covers the metric table alone, so wait for the chart
            // itself to avoid snapshotting before it appears.
            waitForSelector: '[data-attr="experiment-funnel-chart"]',
        },
    },
    decorators: [
        mswDecorator({
            get: {
                [`/api/projects/:team_id/experiments/${EXPERIMENT_STOPPED_WITH_LONG_CONCLUSION.id}/`]:
                    EXPERIMENT_STOPPED_WITH_LONG_CONCLUSION,
                [`/api/projects/:team_id/experiment_holdouts`]: [],
                [`/api/projects/:team_id/experiment_saved_metrics/`]: [],
                [`/api/projects/:team_id/feature_flags/${EXPERIMENT_STOPPED_WITH_LONG_CONCLUSION.feature_flag.id}/`]:
                    {},
                [`/api/projects/:team_id/feature_flags/${EXPERIMENT_STOPPED_WITH_LONG_CONCLUSION.feature_flag.id}/status/`]:
                    {},
                [`/api/environments/:team_id/default_release_conditions/`]: [],
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

export const ExperimentStoppedWithLongConclusion: Story = {}
