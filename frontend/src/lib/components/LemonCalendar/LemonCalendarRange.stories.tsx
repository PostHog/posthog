import React, { useState } from 'react'
import { ComponentMeta, ComponentStory } from '@storybook/react'
import { LemonCalendarRange, LemonCalendarRangeProps } from 'lib/components/LemonCalendar/LemonCalendarRange'
import { Popup } from 'lib/components/Popup/Popup'
import { LemonButton } from 'lib/components/LemonButton'
import { dayjs } from 'lib/dayjs'
import { formatDateRange } from 'lib/utils'

export default {
    title: 'Lemon UI/Lemon Calendar/Lemon Calendar Range',
    component: LemonCalendarRange,
} as ComponentMeta<typeof LemonCalendarRange>

const BasicTemplate: ComponentStory<typeof LemonCalendarRange> = (props: LemonCalendarRangeProps) => {
    const [value, setValue] = useState([
        dayjs().subtract(10, 'day').format('YYYY-MM-DD'),
        dayjs().subtract(4, 'day').format('YYYY-MM-DD'),
    ] as [string, string] | null)
    const [visible, setVisible] = useState(true)

    return (
        // eslint-disable-next-line react/forbid-dom-props
        <div style={{ paddingBottom: 500 }}>
            <Popup
                actionable
                overlay={
                    <LemonCalendarRange
                        {...props}
                        value={value}
                        onChange={(value) => {
                            setValue(value)
                            setVisible(false)
                        }}
                        onClose={() => setVisible(false)}
                    />
                }
                visible={visible}
                onClickOutside={() => setVisible(false)}
            >
                <LemonButton type="secondary" onClick={() => setVisible(!visible)}>
                    {value ? formatDateRange(dayjs(value[0]), dayjs(value[1])) : ''}
                </LemonButton>
            </Popup>
        </div>
    )
}

export const LemonCalendarRange_ = BasicTemplate.bind({})
LemonCalendarRange_.args = {}
