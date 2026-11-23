import type { Meta, StoryObj } from '@storybook/react'

import { TraceToolsCell } from './TraceToolsCell'

const meta: Meta<typeof TraceToolsCell> = {
    title: 'Scenes-App/AI observability/Traces/Trace tools cell',
    component: TraceToolsCell,
    parameters: { testOptions: { snapshotBrowsers: [] } },
    args: { tools: ['search_docs', 'read_file'] },
}
export default meta

type Story = StoryObj<typeof TraceToolsCell>

export const AFewTools: Story = {}

export const MoreThanThree: Story = {
    args: { tools: ['search_docs', 'read_file', 'run_sql', 'send_email', 'create_ticket'] },
}

export const NarrowContainer: Story = {
    args: { tools: ['search_knowledge_base_articles', 'lookup_customer_subscription', 'run_sql', 'send_email'] },
    decorators: [
        (StoryComponent) => (
            <div className="w-40">
                <StoryComponent />
            </div>
        ),
    ],
}
