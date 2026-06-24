import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'

import { DatePicker, DatePickerProps } from './DatePicker'

const quillEnabled = { mockDate: '2023-01-26', featureFlags: [FEATURE_FLAGS.QUILL_DATE_PICKER] }

type Story = StoryObj<typeof DatePicker>
const meta: Meta<typeof DatePicker> = {
    title: 'Components/Date picker',
    component: DatePicker,
    parameters: {
        mockDate: '2023-01-26',
    },
    tags: ['autodocs'],
}
export default meta

function Template(props: Partial<DatePickerProps>): JSX.Element {
    const [value, setValue] = useState<dayjs.Dayjs | null>(props.value ?? null)
    return (
        <div className="w-80">
            <DatePicker {...props} value={value} onChange={setValue} />
        </div>
    )
}

export const Empty: Story = { render: () => <Template placeholder="Select a date" /> }

export const WithValue: Story = { render: () => <Template value={dayjs('2023-01-15')} /> }

export const Clearable: Story = { render: () => <Template value={dayjs('2023-01-15')} clearable /> }

export const WithTime: Story = {
    render: () => <Template value={dayjs('2023-01-15')} granularity="minute" showTimeToggle />,
}

export const PastOnly: Story = { render: () => <Template placeholder="Select a past date" selectionPeriod="past" /> }

export const QuillEmpty: Story = {
    render: () => <Template placeholder="Select a date" />,
    parameters: quillEnabled,
}

export const QuillWithValue: Story = {
    render: () => <Template value={dayjs('2023-01-15')} clearable />,
    parameters: quillEnabled,
}

export const QuillWithTime: Story = {
    render: () => <Template value={dayjs('2023-01-15T09:30')} granularity="minute" showTimeToggle />,
    parameters: quillEnabled,
}
