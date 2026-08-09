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

/** The date variable's calendar is much taller than the Update button next to it. Guards against the
 *  button stretching to the calendar's height. */
export const DateVariableInput: Story = {
    args: { variable: dateVariable },
}
