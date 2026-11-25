import type { Decorator, Meta, StoryObj } from '@storybook/react'

import { ready } from '../../traces/testFixtures'
import { makeSessionPreview } from '../testFixtures'
import { SessionTitle } from './SessionTitle'

const SESSION_ID = 'session-1'

const framed: Decorator = (StoryComponent, { parameters }) => (
    <div className="rounded border p-2" style={{ width: parameters.frameWidth ?? 320 }}>
        <StoryComponent />
    </div>
)

const meta: Meta<typeof SessionTitle> = {
    title: 'Scenes-App/AI observability/Sessions/Session title',
    component: SessionTitle,
    parameters: { testOptions: { snapshotBrowsers: [] } },
    args: { title: ready(makeSessionPreview(SESSION_ID)) },
    decorators: [framed],
}
export default meta

type Story = StoryObj<typeof SessionTitle>

export const Ready: Story = {}

export const LongTitleTruncates: Story = {
    args: {
        title: ready(
            makeSessionPreview(SESSION_ID, {
                input: 'Why was my invoice higher this month than last month, and who added the two extra seats?',
            })
        ),
    },
}

export const Untitled: Story = { args: { title: ready(makeSessionPreview(SESSION_ID, { input: null })) } }

export const Loading: Story = {
    args: { title: { status: 'loading' } },
    parameters: { testOptions: { snapshotBrowsers: [], waitForLoadersToDisappear: false } },
}

export const LoadError: Story = { args: { title: { status: 'error' } } }

export const Narrow: Story = { parameters: { frameWidth: 160 } }
