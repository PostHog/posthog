import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { dayjs } from 'lib/dayjs'
import { LemonCalendarRangeProps } from 'lib/lemon-ui/LemonCalendarRange/LemonCalendarRange'
import { formatDateRange } from 'lib/utils'

import { LemonCalendarRangeInline } from './LemonCalendarRangeInline'

type Story = StoryObj<typeof meta>
const meta: Meta<typeof LemonCalendarRangeInline> = {
    title: 'Lemon UI/Lemon Calendar/Lemon Calendar Range Inline',
    component: LemonCalendarRangeInline,
    parameters: {
        mockDate: '2023-01-26',
    },
    tags: ['autodocs'],
    render: (props: LemonCalendarRangeProps) => {
        const [value, setValue] = useState([dayjs('2022-08-11'), dayjs('2022-08-26')] as
            | [dayjs.Dayjs, dayjs.Dayjs]
            | null)

        return (
            <>
                <LemonCalendarRangeInline
                    {...props}
                    value={value}
                    onChange={(value) => {
                        setValue(value)
                    }}
                />

                <p className="mt-2">Value is: {value ? formatDateRange(...value) : ''}</p>
            </>
        )
    },
}
export default meta

export const LemonCalendarRangeInline_: Story = {
    args: {},
}
