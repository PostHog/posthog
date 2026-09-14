import type { Meta, StoryObj } from '@storybook/react'

import { MaterializationRunError } from './MaterializationRunError'

const meta: Meta<typeof MaterializationRunError> = {
    title: 'Scenes-App/Data Warehouse/Materialization run error',
    component: MaterializationRunError,
}
export default meta

type Story = StoryObj<typeof MaterializationRunError>

const FAILED_ERROR = [
    'ClickHouse error: Code 62. DB::Exception: Syntax error: failed at position 118 (line 4, col 5)',
    "Unmatched parentheses: ')'",
    'Expected one of: token, Comma, Arrow, Dot, ClosingRoundBracket',
].join('\n')

export const FailedRun: Story = {
    render: () => <MaterializationRunError error={FAILED_ERROR} status="Failed" />,
}

export const CompletedRunWithWarning: Story = {
    render: () => <MaterializationRunError error="Warning: query returned no results" status="Completed" />,
}
