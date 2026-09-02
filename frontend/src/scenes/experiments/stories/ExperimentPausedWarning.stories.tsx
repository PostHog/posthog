import { Meta, StoryObj } from '@storybook/react'

import { makeDelay } from 'lib/utils/async'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import EXPERIMENT_WITH_FUNNEL_METRIC from '~/mocks/fixtures/api/experiments/experiment_with_funnel_metric.json'

// A launched experiment whose flag has been disabled, so the warning banner offers to resume it.
const PAUSED_EXPERIMENT = {
    ...EXPERIMENT_WITH_FUNNEL_METRIC,
    feature_flag: { ...EXPERIMENT_WITH_FUNNEL_METRIC.feature_flag, active: false },
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Experiments',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2025-06-01',
        pageUrl: urls.experiment(PAUSED_EXPERIMENT.id),
        // :visible because LemonBanner renders the action twice (inline + stacked, same data-attr)
        // and Playwright's non-strict wait only checks the first match, which CSS may be hiding.
        testOptions: { waitForSelector: '[data-attr="experiment-warning-resume-experiment"]:visible' },
    },
    decorators: [
        mswDecorator({
            get: {
                [`/api/projects/:team_id/experiments/${PAUSED_EXPERIMENT.id}/`]: PAUSED_EXPERIMENT,
                '/api/projects/:team_id/experiment_holdouts': [],
                '/api/projects/:team_id/experiment_saved_metrics/': [],
                [`/api/projects/:team_id/feature_flags/${PAUSED_EXPERIMENT.feature_flag.id}/`]: {},
                [`/api/projects/:team_id/feature_flags/${PAUSED_EXPERIMENT.feature_flag.id}/status/`]: {},
                '/api/environments/:team_id/default_release_conditions/': [],
            },
            post: {
                '/api/environments/:team_id/query/:kind': [200, { results: [] }],
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

export const ExperimentPausedWarning: Story = { play: makeDelay(700) }

// At mobile width the banner stacks: content on top, full-width resume button underneath
// (LemonBanner's @container breakpoint swaps the inline button for the stacked one).
export const ExperimentPausedWarningMobile: Story = {
    parameters: {
        // waitForSelector is inherited from the meta parameters via Storybook's deep merge.
        testOptions: {
            viewport: { width: 390, height: 844 },
        },
    },
    play: makeDelay(700),
}
