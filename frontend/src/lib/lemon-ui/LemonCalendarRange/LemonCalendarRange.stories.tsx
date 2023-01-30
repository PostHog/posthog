import { useState } from 'react'
import { ComponentMeta, ComponentStory } from '@storybook/react'
import { LemonCalendarRange, LemonCalendarRangeProps } from 'lib/lemon-ui/LemonCalendarRange/LemonCalendarRange'
import { Popup } from 'lib/lemon-ui/Popup/Popup'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { dayjs } from 'lib/dayjs'
import { formatDateRange } from 'lib/utils'

export default {
    title: 'Lemon UI/Lemon Calendar/Lemon Calendar Range',
    component: LemonCalendarRange,
    parameters: {
        mockDate: '2023-01-26',
        chromatic: { disableSnapshot: false },
    },
} as ComponentMeta<typeof LemonCalendarRange>

const BasicTemplate: ComponentStory<typeof LemonCalendarRange> = (props: LemonCalendarRangeProps) => {
    const [value, setValue] = useState([dayjs('2022-08-11'), dayjs('2022-08-26')] as LemonCalendarRangeProps['value'])
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
                    {value ? formatDateRange(...value) : ''}
                </LemonButton>
            </Popup>
        </div>
    )
}

export const LemonCalendarRange_ = BasicTemplate.bind({})
LemonCalendarRange_.args = {}
