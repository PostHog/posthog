import { Meta, StoryObj } from '@storybook/react'

import { PathCleaningRulesDebugger } from './PathCleaningRulesDebugger'

const meta: Meta<typeof PathCleaningRulesDebugger> = {
    title: 'Filters/PathCleaningRulesDebugger',
    component: PathCleaningRulesDebugger,
}
export default meta

export const Default: StoryObj<typeof PathCleaningRulesDebugger> = {
    args: {
        testPath: '/insights/my-dashboard/dashboard',
        filters: [
            { alias: 'dashboard', regex: '/insights/\\w+/dashboard$', order: 0 },
            { alias: 'feature-flags', regex: '/feature_flags/\\d+$', order: 1 },
            { alias: 'recordings', regex: '/replay/\\w+', order: 2 },
            { alias: '', regex: '/api/v1/.*', order: 3 }, // Empty alias
            { alias: 'invalid', regex: '[invalid(regex', order: 4 }, // Invalid regex
        ],
        finalResult: 'dashboard',
    },
}
