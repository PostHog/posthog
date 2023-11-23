import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { dayjs } from 'lib/dayjs'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCalendarRange, LemonCalendarRangeProps } from 'lib/lemon-ui/LemonCalendarRange/LemonCalendarRange'
import { Popover } from 'lib/lemon-ui/Popover/Popover'
import { formatDateRange } from 'lib/utils'
import { useState } from 'react'

type Story = StoryObj<typeof LemonCalendarRange>
const meta: Meta<typeof LemonCalendarRange> = {
    title: 'Lemon UI/Lemon Calendar/Lemon Calendar Range',
    component: LemonCalendarRange,
    parameters: {
        mockDate: '2023-01-26',
    },
    tags: ['autodocs'],
}
export default meta

const BasicTemplate: StoryFn<typeof LemonCalendarRange> = (props: LemonCalendarRangeProps) => {
    const [value, setValue] = useState([dayjs('2022-08-11'), dayjs('2022-08-26')] as LemonCalendarRangeProps['value'])
    const [visible, setVisible] = useState(true)

    return (
        // eslint-disable-next-line react/forbid-dom-props
        <div style={{ paddingBottom: 500 }}>
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
}

export const LemonCalendarRange_: Story = BasicTemplate.bind({})
LemonCalendarRange_.args = {}
