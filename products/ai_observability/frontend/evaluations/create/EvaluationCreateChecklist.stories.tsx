import type { Meta, StoryObj } from '@storybook/react'

import { withWidth } from '../../redesign/trace/storyFixtures'
import { EvaluationCreateChecklist } from './EvaluationCreateChecklist'
import { NARROW_PANEL_WIDTH, PANEL_WIDTH, storyChecklist } from './previewStoryFixtures'

const meta: Meta<typeof EvaluationCreateChecklist> = {
    title: 'Scenes-App/AI observability/New evaluation/Checklist',
    component: EvaluationCreateChecklist,
    decorators: [withWidth(PANEL_WIDTH)],
    parameters: { testOptions: { snapshotBrowsers: [] } },
    args: { checklist: storyChecklist({}), startsPaused: false, onOpen: () => {} },
}
export default meta

type Story = StoryObj<typeof EvaluationCreateChecklist>

export const Ready: Story = {}
export const ReadyPaused: Story = { args: { startsPaused: true } }
export const CodeDoesNotCompile: Story = {
    args: { checklist: storyChecklist({ criteria: { done: false, todo: 'Fix the code so it compiles' } }) },
}
export const WouldNotRun: Story = {
    args: {
        checklist: storyChecklist({
            sampling: { warning: 'No matching generation has a session ID, so it would not run' },
        }),
    },
    decorators: [withWidth(NARROW_PANEL_WIDTH)],
}
