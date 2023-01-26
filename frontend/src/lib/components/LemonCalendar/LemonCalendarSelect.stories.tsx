import { useState } from 'react'
import { ComponentMeta, ComponentStory } from '@storybook/react'
import { LemonCalendarSelect, LemonCalendarSelectProps } from 'lib/components/LemonCalendar/LemonCalendarSelect'
import { Popup } from 'lib/components/Popup/Popup'
import { LemonButton } from 'lib/components/LemonButton'
import { dayjs } from 'lib/dayjs'
import { formatDate } from 'lib/utils'

export default {
    title: 'Lemon UI/Lemon Calendar/Lemon Calendar Select',
    component: LemonCalendarSelect,
    parameters: {
        mockDate: '2023-01-26',
        chromatic: { disableSnapshot: false },
    },
} as ComponentMeta<typeof LemonCalendarSelect>

const BasicTemplate: ComponentStory<typeof LemonCalendarSelect> = (props: LemonCalendarSelectProps) => {
    const [value, setValue] = useState(dayjs().subtract(10, 'day'))
    const [visible, setVisible] = useState(true)

    return (
        // eslint-disable-next-line react/forbid-dom-props
        <div style={{ paddingBottom: 500 }}>
            <Popup
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
            </Popup>
        </div>
    )
}

export const LemonCalendarSelect_ = BasicTemplate.bind({})
LemonCalendarSelect_.args = {}
