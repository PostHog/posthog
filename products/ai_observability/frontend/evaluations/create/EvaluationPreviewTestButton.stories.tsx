import type { Meta, StoryObj } from '@storybook/react'

import { AccessControlLevel } from '~/types'

import { withWidth } from '../../redesign/trace/storyFixtures'
import { EvaluationPreviewTestButton } from './EvaluationPreviewTestButton'
import { NARROW_PANEL_WIDTH, PANEL_WIDTH } from './previewStoryFixtures'

const meta: Meta<typeof EvaluationPreviewTestButton> = {
    title: 'Scenes-App/AI observability/New evaluation/Preview test button',
    component: EvaluationPreviewTestButton,
    decorators: [withWidth(PANEL_WIDTH)],
    parameters: { testOptions: { snapshotBrowsers: [] } },
    args: {
        count: 3,
        unit: 'generation',
        loading: false,
        userAccessLevel: AccessControlLevel.Editor,
        onTest: () => {},
    },
}
export default meta

type Story = StoryObj<typeof EvaluationPreviewTestButton>

export const Ready: Story = {}
export const Testing: Story = { args: { loading: true } }
export const NothingToTest: Story = { args: { count: 0, disabledReason: 'No sessions to test', unit: 'session' } }
export const Viewer: Story = { args: { userAccessLevel: AccessControlLevel.Viewer } }
export const Narrow: Story = { args: { unit: 'session' }, decorators: [withWidth(NARROW_PANEL_WIDTH)] }
