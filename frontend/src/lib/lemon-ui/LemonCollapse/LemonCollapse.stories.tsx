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

export const LemonCollapse = Template.bind({})
LemonCollapse.args = {}
