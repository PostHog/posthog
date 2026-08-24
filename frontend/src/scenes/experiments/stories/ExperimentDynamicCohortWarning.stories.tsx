import { Meta, StoryObj } from '@storybook/react'
import { within } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'

import { makeDelay } from 'lib/utils/async'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import EXPERIMENT_WITH_MEAN_METRIC from '~/mocks/fixtures/api/experiments/experiment_with_mean_metric.json'
import EXPOSURE_QUERY_RESULT from '~/mocks/fixtures/api/experiments/exposure_query_result.json'
import MEAN_METRIC_RESULT from '~/mocks/fixtures/api/experiments/mean_metric_result.json'
import { NodeKind } from '~/queries/schema/schema-general'
import { PropertyFilterType, PropertyOperator } from '~/types'

const DYNAMIC_COHORT = { id: 42, name: 'Signups in tier-3 countries' }

// The banner is gated on `dynamic_cohort_risk`, which the exposures runner only emits when the
// exposure criteria references a cohort with `is_static: false`.
const EXPOSURE_RESULT_WITH_DYNAMIC_COHORT_RISK = {
    ...EXPOSURE_QUERY_RESULT,
    dynamic_cohort_risk: { cohorts: [DYNAMIC_COHORT] },
}

// The modal warning is resolved client-side instead: it reads the cohort off `cohortsModel`, so
// the criteria must carry the cohort filter and the cohort must be dynamic.
const EXPERIMENT_WITH_COHORT_EXPOSURE_CRITERIA = {
    ...EXPERIMENT_WITH_MEAN_METRIC,
    exposure_criteria: {
        filterTestAccounts: true,
        exposure_config: {
            kind: NodeKind.ExperimentEventExposureConfig,
            event: '$feature_flag_called',
            properties: [
                {
                    key: 'id',
                    type: PropertyFilterType.Cohort,
                    value: DYNAMIC_COHORT.id,
                    operator: PropertyOperator.In,
                },
            ],
        },
    },
}

const queryMock = async ({ request }: { request: Request }): Promise<[number, Record<string, any>]> => {
    const body = (await request.json()) as Record<string, any>
    if (body.query.kind === NodeKind.ExperimentExposureQuery) {
        return [200, EXPOSURE_RESULT_WITH_DYNAMIC_COHORT_RISK]
    }
    return [200, MEAN_METRIC_RESULT]
}

const baseMocks = {
    [`/api/projects/:team_id/experiment_holdouts`]: [],
    [`/api/projects/:team_id/experiment_saved_metrics/`]: [],
    [`/api/projects/:team_id/feature_flags/${EXPERIMENT_WITH_MEAN_METRIC.feature_flag.id}/`]: {},
    [`/api/projects/:team_id/feature_flags/${EXPERIMENT_WITH_MEAN_METRIC.feature_flag.id}/status/`]: {},
    [`/api/environments/:team_id/default_release_conditions/`]: [],
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Experiments',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2025-01-27',
        pageUrl: urls.experiment(EXPERIMENT_WITH_MEAN_METRIC.id),
    },
    decorators: [
        mswDecorator({
            get: {
                ...baseMocks,
                [`/api/projects/:team_id/experiments/${EXPERIMENT_WITH_MEAN_METRIC.id}/`]: EXPERIMENT_WITH_MEAN_METRIC,
            },
            post: { '/api/environments/:team_id/query/:kind': queryMock },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

export const ExperimentDynamicCohortWarning: Story = {}

export const ExperimentDynamicCohortCriteriaModal: Story = {
    decorators: [
        mswDecorator({
            get: {
                ...baseMocks,
                [`/api/projects/:team_id/experiments/${EXPERIMENT_WITH_MEAN_METRIC.id}/`]:
                    EXPERIMENT_WITH_COHORT_EXPOSURE_CRITERIA,
                '/api/projects/:team_id/cohorts/': {
                    count: 1,
                    results: [{ ...DYNAMIC_COHORT, is_static: false, groups: [], filters: undefined }],
                },
            },
            post: { '/api/environments/:team_id/query/:kind': queryMock },
        }),
    ],
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await makeDelay(500)()
        await userEvent.click(await canvas.findByText('Edit exposure criteria'))
        await makeDelay(500)()
    },
}
