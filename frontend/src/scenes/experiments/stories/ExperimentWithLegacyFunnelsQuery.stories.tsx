import { Meta, StoryObj } from '@storybook/react'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import EXPERIMENT_WITH_FUNNELS_QUERY from '~/mocks/fixtures/api/experiments/experiment_with_funnels_query.json'
import EXPOSURE_QUERY_RESULT from '~/mocks/fixtures/api/experiments/exposure_query_result.json'
import FUNNELS_QUERY_RESULT from '~/mocks/fixtures/api/experiments/funnels_query_result.json'
import { NodeKind } from '~/queries/schema/schema-general'
import { makeDelay } from 'lib/utils'

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Experiments',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2025-01-27',
        pageUrl: urls.experiment(EXPERIMENT_WITH_FUNNELS_QUERY.id),
    },
    decorators: [
        mswDecorator({
            get: {
                [`/api/projects/:team_id/experiments/${EXPERIMENT_WITH_FUNNELS_QUERY.id}/`]:
                    EXPERIMENT_WITH_FUNNELS_QUERY,
                [`/api/projects/:team_id/experiment_holdouts`]: [],
                [`/api/projects/:team_id/experiment_saved_metrics/`]: [],
                [`/api/projects/:team_id/feature_flags/${EXPERIMENT_WITH_FUNNELS_QUERY.feature_flag.id}/`]: {},
                [`/api/projects/:team_id/feature_flags/${EXPERIMENT_WITH_FUNNELS_QUERY.feature_flag.id}/status/`]: {},
            },
            post: {
                '/api/environments/:team_id/query': (req, res, ctx) => {
                    const body = req.body as Record<string, any>

                    if (body.query.kind === NodeKind.ExperimentExposureQuery) {
                        return res(ctx.json(EXPOSURE_QUERY_RESULT))
                    }

                    return res(ctx.json(FUNNELS_QUERY_RESULT))
                },
            },
        }),
    ],
}
export default meta

type Story = StoryObj<typeof meta>

// Small delay to ensure charts render completely
export const ExperimentWithLegacyFunnelsQuery: Story = { play: makeDelay(500) }
