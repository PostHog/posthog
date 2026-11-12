import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { ActivityQueryEditor } from './ActivityQueryEditor'

const meta: Meta<typeof ActivityQueryEditor> = {
    title: 'Customer analytics/Product activity/Query editor',
    component: ActivityQueryEditor,
    args: {
        queryKey: 'activity-editor-story',
        query: 'SELECT {account_id}',
        bindings: { values: { account_id: 'example-account' } },
        helpText: 'Use {account_id} to select this account.',
        onRun: () => {},
    },
    render: function Render(args) {
        const [query, setQuery] = useState(args.query)
        return (
            <div className="w-128 flex flex-col gap-3">
                <ActivityQueryEditor {...args} query={query} onChange={setQuery} />
            </div>
        )
    },
    parameters: {
        testOptions: { snapshotBrowsers: [], waitForSelector: '.CodeEditor[data-editor-ready="true"]' },
    },
}
export default meta
export const AccountQuery: StoryObj<typeof meta> = {}
