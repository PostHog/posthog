import React, { useState } from 'react'
import { ComponentMeta, ComponentStory } from '@storybook/react'
import { LemonCalendarRangeProps } from 'lib/components/LemonCalendarRange/LemonCalendarRange'
import { dayjs } from 'lib/dayjs'
import { formatDateRange } from 'lib/utils'
import { LemonCalendarRangeInline } from './LemonCalendarRangeInline'

export default {
    title: 'Lemon UI/Lemon Calendar/Lemon Calendar Range Inline',
    component: LemonCalendarRangeInline,
} as ComponentMeta<typeof LemonCalendarRangeInline>

const BasicTemplate: ComponentStory<typeof LemonCalendarRangeInline> = (props: LemonCalendarRangeProps) => {
    const [value, setValue] = useState(['2022-08-11', '2022-08-26'] as [string, string] | null)

    return (
        <>
            <LemonCalendarRangeInline
                {...props}
                value={value}
                onChange={(value) => {
                    setValue(value)
                }}
            />

            <p className="mt-2">Value is: {value ? formatDateRange(dayjs(value[0]), dayjs(value[1])) : ''}</p>
        </>
    )
}

export const LemonCalendarRangeInline_ = BasicTemplate.bind({})
LemonCalendarRangeInline_.args = {}
