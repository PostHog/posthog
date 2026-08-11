import { Meta, StoryObj } from '@storybook/react'

import { PathCleaningRulesDebugger, PathCleaningRulesDebuggerProps } from './PathCleaningRulesDebugger'

const meta: Meta<PathCleaningRulesDebuggerProps> = {
    title: 'Filters/PathCleaningRulesDebugger',
    component: PathCleaningRulesDebugger,
}
export default meta

export const Default: StoryObj<PathCleaningRulesDebuggerProps> = {
    args: {
        testPath: '/insights/my-dashboard/dashboard',
        filters: [
            { alias: 'dashboard', regex: '/insights/\\w+/dashboard$', order: 0 },
            { alias: 'feature-flags', regex: '/feature_flags/\\d+$', order: 1 },
            { alias: 'recordings', regex: '/replay/\\w+', order: 2 },
            { alias: '', regex: '/api/v1/.*', order: 3 }, // Empty alias
            { alias: 'invalid', regex: '[invalid(regex', order: 4 }, // Invalid regex
            { alias: '/users/\\1', regex: '(?i)/Users/(\\d+)', order: 5 }, // Inline re2 flag group and a capture group
            { alias: '/orders/\\1', regex: '/orders/(?P<id>\\d+)', order: 6 }, // Valid re2 the preview can't run
        ],
        finalResult: 'dashboard',
    },
}
