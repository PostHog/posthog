import type { Meta, StoryObj } from '@storybook/react'

import { ActivityQueryActions } from './ActivityQueryActions'

const meta: Meta<typeof ActivityQueryActions> = {
    title: 'Customer analytics/Product activity/Query actions',
    component: ActivityQueryActions,
    args: {
        loading: true,
        saveError: 'Wait for the query to finish.',
        onRun: () => {},
        onSave: () => {},
        onCancel: () => {},
        dataAttributes: { run: 'activity-story-run', save: 'activity-story-save' },
    },
    parameters: { testOptions: { snapshotBrowsers: [] } },
}
export default meta
export const QueryRunning: StoryObj<typeof meta> = {}
