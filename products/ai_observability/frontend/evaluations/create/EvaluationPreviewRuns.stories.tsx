import type { Meta, StoryObj } from '@storybook/react'

import { withWidth } from '../../redesign/trace/storyFixtures'
import { EvaluationPreviewRuns } from './EvaluationPreviewRuns'
import { NARROW_PANEL_WIDTH, PANEL_WIDTH, storyRuns } from './previewStoryFixtures'

const ERROR = "Global 'generatoin' is not defined"

const meta: Meta<typeof EvaluationPreviewRuns> = {
    title: 'Scenes-App/AI observability/New evaluation/Preview runs',
    component: EvaluationPreviewRuns,
    decorators: [withWidth(PANEL_WIDTH)],
    parameters: { testOptions: { snapshotBrowsers: [] } },
    args: {
        unit: 'generation',
        runs: storyRuns([
            { outcome: 'pass', value: 'True', detail: 'The answer names the reset link.' },
            { outcome: 'fail', value: 'False', detail: 'The answer skips the total.' },
            { outcome: 'error', value: 'N/A', detail: ERROR },
        ]),
        loading: false,
        loadFailed: false,
        noneInSample: false,
        live: true,
        testing: false,
        rowProps: () => ({}),
    },
}
export default meta

type Story = StoryObj<typeof EvaluationPreviewRuns>

export const Results: Story = {}
export const NotTestedYet: Story = { args: { runs: storyRuns([null, null, null]), live: false } }
export const EveryRunErrored: Story = {
    args: {
        runs: storyRuns([
            { outcome: 'error', value: 'N/A', detail: ERROR },
            { outcome: 'error', value: 'N/A', detail: ERROR },
        ]),
    },
}
export const UngradedScores: Story = {
    args: {
        runs: storyRuns([
            { outcome: null, value: '4.2', detail: null },
            { outcome: null, value: '3', detail: null },
        ]),
    },
}
export const Loading: Story = { args: { runs: [], loading: true } }
export const LoadFailed: Story = { args: { runs: [], loadFailed: true } }
export const NothingMatched: Story = { args: { runs: [], unit: 'trace' } }
export const NoneInSample: Story = { args: { runs: [], unit: 'trace', noneInSample: true } }
export const Narrow: Story = { decorators: [withWidth(NARROW_PANEL_WIDTH)] }
