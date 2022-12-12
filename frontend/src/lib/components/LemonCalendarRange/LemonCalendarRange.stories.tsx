import { useState } from 'react'
import { ComponentMeta, ComponentStory } from '@storybook/react'
import { LemonCalendarRange, LemonCalendarRangeProps } from 'lib/components/LemonCalendarRange/LemonCalendarRange'
import { Popup } from 'lib/components/Popup/Popup'
import { LemonButton } from 'lib/components/LemonButton'
import { dayjs } from 'lib/dayjs'
import { formatDateRange } from 'lib/utils'

export default {
    title: 'Lemon UI/Lemon Calendar/Lemon Calendar Range',
    component: LemonCalendarRange,
    parameters: { chromatic: { disableSnapshot: false } },
} as ComponentMeta<typeof LemonCalendarRange>

const BasicTemplate: ComponentStory<typeof LemonCalendarRange> = (props: LemonCalendarRangeProps) => {
    const [value, setValue] = useState(['2022-08-11', '2022-08-26'] as [string, string] | null)
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
