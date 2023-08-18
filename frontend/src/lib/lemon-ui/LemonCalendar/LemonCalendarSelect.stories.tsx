import { useState } from 'react'
import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { LemonCalendarSelect, LemonCalendarSelectProps } from 'lib/lemon-ui/LemonCalendar/LemonCalendarSelect'
import { Popover } from 'lib/lemon-ui/Popover/Popover'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { dayjs } from 'lib/dayjs'
import { formatDate } from 'lib/utils'

type Story = StoryObj<typeof LemonCalendarSelect>
const meta: Meta<typeof LemonCalendarSelect> = {
    title: 'Lemon UI/Lemon Calendar/Lemon Calendar Select',
    component: LemonCalendarSelect,
    parameters: {
        mockDate: '2023-01-26',
    },
    tags: ['autodocs'],
}
export default meta

const BasicTemplate: StoryFn<typeof LemonCalendarSelect> = (props: LemonCalendarSelectProps) => {
    const [value, setValue] = useState(dayjs().subtract(10, 'day'))
    const [visible, setVisible] = useState(true)

    return (
        // eslint-disable-next-line react/forbid-dom-props
        <div style={{ paddingBottom: 500 }}>
            <Popover
                actionable
                overlay={
                    <LemonCalendarSelect
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
                    {formatDate(value)}
                </LemonButton>
            </Popover>
        </div>
    )
}

export const LemonCalendarSelect_: Story = {
    render: BasicTemplate,
    args: {},
}
