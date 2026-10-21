import type { Meta, StoryObj } from '@storybook/react'

import { QuestionRunResult } from './QuestionRunResult'

const meta: Meta<typeof QuestionRunResult> = {
    title: 'Products/Data quality/Question run result',
    component: QuestionRunResult,
    args: {
        result: {
            status: 'passed',
            examined_row_count: 5000,
            failed_row_count: 20,
            failure_rate: 0.004,
            unique_input_count: 400,
            reused_decision_count: 350,
            new_decision_count: 50,
            completed_chunk_count: 4,
            total_chunk_count: 4,
            coverage_complete: true,
        },
    },
}
export default meta

type Story = StoryObj<typeof meta>
export const Complete: Story = {}
export const Incomplete: Story = {
    args: {
        result: {
            ...meta.args!.result!,
            status: 'errored',
            examined_row_count: 4000,
            failed_row_count: 15,
            failure_rate: null,
            completed_chunk_count: 3,
            coverage_complete: false,
        },
    },
}
export const Empty: Story = {
    args: {
        result: {
            status: 'skipped',
            examined_row_count: 0,
            failed_row_count: 0,
            failure_rate: null,
            unique_input_count: 0,
            reused_decision_count: 0,
            new_decision_count: 0,
            completed_chunk_count: 0,
            total_chunk_count: 0,
            coverage_complete: true,
        },
    },
}
