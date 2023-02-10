import { ComponentMeta, ComponentStory } from '@storybook/react'
import { useState } from 'react'
import { LemonTab, LemonTabs as LemonTabsComponent } from './LemonTabs'

export default {
    title: 'Lemon UI/Lemon Tabs',
    component: LemonTabsComponent,
    argTypes: {
        tabs: {
            control: {
                type: 'object',
            },
            defaultValue: [
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
        // Show value and onChange, but disable editing as they're handled by the template
        value: { control: { disable: true } },
        onChange: { control: { disable: true } },
    },
} as ComponentMeta<typeof LemonTabsComponent>

const Template: ComponentStory<typeof LemonTabsComponent> = (props) => {
    const [activeKey, setActiveKey] = useState(props.tabs[0].key)

    return <LemonTabsComponent {...props} activeKey={activeKey} onChange={(newValue) => setActiveKey(newValue)} />
}

export const LemonTabs = Template.bind({})
LemonTabs.args = {}
