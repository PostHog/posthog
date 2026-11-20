import type { Meta, StoryObj } from '@storybook/react'
import { fireEvent, within } from '@testing-library/dom'

import { mswDecorator } from '~/mocks/browser'

import { ScorerVersionHistory } from './ScorerVersionHistory'
import { historyDefinition, historyVersions } from './scorerVersionHistory.fixtures'

const meta: Meta<typeof ScorerVersionHistory> = {
    title: 'AI observability/Scorer version history',
    component: ScorerVersionHistory,
    parameters: { testOptions: { snapshotBrowsers: [] } },
    args: { definition: historyDefinition },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team/llm_analytics/score_definitions/:id/versions/': {
                    count: 2,
                    results: historyVersions,
                    next_cursor: null,
                    next: null,
                    previous: null,
                },
            },
        }),
    ],
}
export default meta
type Story = StoryObj<typeof meta>

export const SavedVersions: Story = {
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        fireEvent.click(await canvas.findByRole('button', { name: 'Version history' }))
        await within(document.body).findByText('Pass ≥ 8')
    },
}
