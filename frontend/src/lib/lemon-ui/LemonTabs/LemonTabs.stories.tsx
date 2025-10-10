import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { LemonButton } from '../LemonButton'
import { LemonTab, LemonTabs as LemonTabsComponent } from './LemonTabs'

type Story = StoryObj<typeof LemonTabsComponent>
const meta: Meta<typeof LemonTabsComponent> = {
    title: 'Lemon UI/Lemon Tabs',
    component: LemonTabsComponent,
    argTypes: {
        tabs: {
            control: {
                type: 'object',
            },
        },
        onChange: { control: { disable: true } },
    },
    tags: ['autodocs'],
    args: {
        tabs: [
            {
                key: 'calendar',
                label: 'Calendar',
                content: <div>Imagine some calendar here. 🗓️</div>,
            },
            {
                key: 'calculator',
                label: 'Calculator',
                tooltip: 'Calculate 2+2, as well as 1/0.',
                content: <div>Imagine some calculator here. 🔢</div>,
            },
            {
                key: 'banana',
                label: 'Banana',
                content: <div>Imagine some banana here. 🍌</div>,
            },
            {
                key: 'settings',
                label: 'Settings',
                content: <div>Imagine some settings here. ⚙️</div>,
            },
        ] as LemonTab<'calendar' | 'calculator' | 'banana' | 'settings'>[],
    },
}
export default meta

const Template: StoryFn<typeof LemonTabsComponent> = (props) => {
    const [activeKey, setActiveKey] = useState((props.tabs[0] as LemonTab<string | number>).key)

    return <LemonTabsComponent {...props} activeKey={activeKey} onChange={(newValue) => setActiveKey(newValue)} />
}

export const Default: Story = Template.bind({})
Default.args = {}

export const Small: Story = Template.bind({})
Small.args = { size: 'small' }

export const RightSlot: Story = Template.bind({})
RightSlot.args = {
    rightSlot: (
        <LemonButton type="secondary" size="small">
            Right slot
        </LemonButton>
    ),
}
