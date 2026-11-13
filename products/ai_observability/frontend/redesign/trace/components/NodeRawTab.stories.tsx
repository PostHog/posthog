import type { Meta, StoryObj } from '@storybook/react'

import { withWidth } from '../storyFixtures'
import { NodeRawTab } from './NodeRawTab'

const meta: Meta<typeof NodeRawTab> = {
    title: 'Scenes-App/AI observability/Trace view/Raw event',
    component: NodeRawTab,
}
export default meta

type Story = StoryObj<typeof NodeRawTab>

export const Default: Story = {
    args: {
        raw: {
            status: 'ready',
            raw: {
                id: 'gen-answer',
                kind: 'generation',
                event: {
                    name: '$ai_generation',
                    uuid: 'gen-answer',
                    timestamp: '2026-09-01T10:15:02Z',
                    properties: { $ai_model: 'gpt-6-luna', $ai_latency: 1.88, $ai_input_tokens: 1822 },
                    ioKeys: { input: null, output: null, tools: null },
                },
            },
        },
    },
}

export const Loading: Story = {
    args: { raw: { status: 'loading' } },
    decorators: [withWidth(720)],
    parameters: { testOptions: { waitForLoadersToDisappear: false } },
}

export const Failed: Story = { args: { raw: { status: 'error', failure: 'failed' } } }

export const NoTraceEvent: Story = {
    args: { raw: { status: 'ready', raw: { id: 'trace-1', kind: 'trace', event: null } } },
}

export const NotFound: Story = {
    args: { raw: { status: 'error', failure: 'not_found' } },
    parameters: { testOptions: { snapshotBrowsers: [] } },
}
