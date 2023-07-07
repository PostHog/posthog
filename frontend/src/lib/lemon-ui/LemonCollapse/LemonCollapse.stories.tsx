import { ComponentMeta, ComponentStory } from '@storybook/react'
import { LemonCollapse as LemonCollapseComponent } from './LemonCollapse'

export default {
    title: 'Lemon UI/Lemon Collapse',
    component: LemonCollapseComponent,
    argTypes: {
        panels: {
            defaultValue: [
                {
                    key: '1',
                    header: 'Panel 1',
                    content: <span>Panel 1 content</span>,
                },
                {
                    key: '2',
                    header: 'Panel 2',
                    content: <span>Panel 2 content</span>,
                },
            ],
        },
    },
} as ComponentMeta<typeof LemonCollapseComponent>

const Template: ComponentStory<typeof LemonCollapseComponent> = (props) => {
    return <LemonCollapseComponent {...props} />
}

export const Single = Template.bind({})
Single.args = { defaultActiveKey: '1' }

export const Multiple = Template.bind({})
Multiple.args = { defaultActiveKeys: ['1', '2'], multiple: true }
