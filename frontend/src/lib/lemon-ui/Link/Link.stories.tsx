import { ComponentMeta, ComponentStory } from '@storybook/react'
import { Link, LinkProps } from './Link'
import { urls } from 'scenes/urls'

export default {
    title: 'Lemon UI/Link',
    component: Link,
    argTypes: {
        children: {
            defaultValue: 'Click me',
        },
    },
} as ComponentMeta<typeof Link>

const BasicTemplate: ComponentStory<typeof Link> = (props: LinkProps) => {
    return <Link {...props} />
}

export const Default = BasicTemplate.bind({})
Default.args = {}

export const ToLink = BasicTemplate.bind({})
ToLink.args = {
    to: urls.projectHomepage(),
}

export const DisabledWithReason = BasicTemplate.bind({})
DisabledWithReason.args = {
    disabledReason: 'Not allowed',
}
