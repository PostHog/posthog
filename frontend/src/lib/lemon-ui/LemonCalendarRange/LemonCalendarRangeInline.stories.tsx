import { useState } from 'react'
import { ComponentMeta, ComponentStory } from '@storybook/react'
import { LemonCalendarRangeProps } from 'lib/lemon-ui/LemonCalendarRange/LemonCalendarRange'
import { dayjs } from 'lib/dayjs'
import { formatDateRange } from 'lib/utils'
import { LemonCalendarRangeInline } from './LemonCalendarRangeInline'

export default {
    title: 'Lemon UI/Lemon Calendar/Lemon Calendar Range Inline',
    component: LemonCalendarRangeInline,
    parameters: {
        mockDate: '2023-01-26',
    },
} as ComponentMeta<typeof LemonCalendarRangeInline>

const BasicTemplate: ComponentStory<typeof LemonCalendarRangeInline> = (props: LemonCalendarRangeProps) => {
    const [value, setValue] = useState([dayjs('2022-08-11'), dayjs('2022-08-26')] as [dayjs.Dayjs, dayjs.Dayjs] | null)

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
}

export const LemonCalendarRangeInline_ = BasicTemplate.bind({})
LemonCalendarRangeInline_.args = {}
