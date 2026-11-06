import { Meta, StoryObj } from '@storybook/react'

import { DateVariable, StringVariable } from '../../types'
import { VariableInput } from './Variables'

const meta: Meta<typeof VariableInput> = {
    title: 'Insights/Variables',
    component: VariableInput,
    parameters: {
        layout: 'centered',
        // The fixed-date calendar marks today, so the snapshot needs a stable clock.
        mockDate: '2024-05-15',
        testOptions: { snapshotBrowsers: ['chromium'] },
    },
    args: {
        showEditingUI: false,
        closePopover: () => {},
        onChange: () => {},
    },
}
export default meta

type Story = StoryObj<typeof VariableInput>

const stringVariable: StringVariable = {
    id: 'string-variable',
    name: 'Chain',
    code_name: 'chain',
    type: 'String',
    default_value: 'ALL',
}

const dateVariable: DateVariable = {
    id: 'date-variable',
    name: 'start',
    code_name: 'start',
    type: 'Date',
    default_value: '2024-05-10',
}

export const StringVariableInput: Story = {
    args: { variable: stringVariable },
}

/** The calendar's own Apply button commits a fixed date, so there is no second commit button here. */
export const DateVariableInput: Story = {
    args: { variable: dateVariable },
}

/** The relative-date tab has no Apply of its own, so it keeps the Update button. Guards against that
 *  button stretching to the height of the column beside it. */
export const RelativeDateVariableInput: Story = {
    args: { variable: { ...dateVariable, default_value: '-7d' } },
}

/** The editing UI shows the variable's HogQL reference on one unbroken line, so a long code name
 *  widens the popover well past its usual 320px. Guards against the calendar growing with it. */
export const DateVariableInputWithLongCodeName: Story = {
    args: {
        showEditingUI: true,
        variable: { ...dateVariable, code_name: 'quarterly_revenue_report_period_start_date' },
    },
}
