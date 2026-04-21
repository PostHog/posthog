import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { dayjs } from 'lib/dayjs'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCalendarRange, LemonCalendarRangeProps } from 'lib/lemon-ui/LemonCalendarRange/LemonCalendarRange'
import { Popover } from 'lib/lemon-ui/Popover/Popover'
import { formatDateRange } from 'lib/utils'

type Story = StoryObj<LemonCalendarRangeProps>
const meta: Meta<LemonCalendarRangeProps> = {
    title: 'Lemon UI/Lemon Calendar/Lemon Calendar Range',
    component: LemonCalendarRange,
    parameters: {
        mockDate: '2023-01-26',
    },
    tags: ['autodocs'],
    render: (props) => {
        const [value, setValue] = useState([
            dayjs('2022-08-11'),
            dayjs('2022-08-26'),
        ] as LemonCalendarRangeProps['value'])
        const [visible, setVisible] = useState(true)

        return (
            <div className="pb-[30rem]">
                <Popover
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
                        {value ? formatDateRange(...value) : ''}
                    </LemonButton>
                </Popover>
            </div>
        )
    },
}
export default meta

export const LemonCalendarRange_: Story = {
    args: {},
}
