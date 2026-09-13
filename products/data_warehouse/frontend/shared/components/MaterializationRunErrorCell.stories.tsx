import type { Meta, StoryObj } from '@storybook/react'

import { MaterializationRunErrorCell } from './MaterializationRunErrorCell'

const meta: Meta<typeof MaterializationRunErrorCell> = {
    title: 'Scenes-App/Data Warehouse/Materialization run error',
    component: MaterializationRunErrorCell,
}
export default meta

type Story = StoryObj<typeof MaterializationRunErrorCell>

const FAILED_ERROR = [
    'ClickHouse error: Code 62. DB::Exception: Syntax error: failed at position 118 (line 4, col 5)',
    "Unmatched parentheses: ')'",
    'Expected one of: token, Comma, Arrow, Dot, ClosingRoundBracket',
].join('\n')

export const FailedRun: Story = {
    render: () => <MaterializationRunErrorCell error={FAILED_ERROR} status="Failed" />,
}

export const CompletedRunWithWarning: Story = {
    render: () => <MaterializationRunErrorCell error="Warning: query returned no results" status="Completed" />,
}
