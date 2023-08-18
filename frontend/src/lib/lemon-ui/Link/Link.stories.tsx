import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { Link, LinkProps } from './Link'
import { urls } from 'scenes/urls'

type Story = StoryObj<typeof Link>
const meta: Meta<typeof Link> = {
    title: 'Lemon UI/Link',
    component: Link,
    args: {
        children: 'Click me',
    },
    tags: ['autodocs'],
}
export default meta

const BasicTemplate: StoryFn<typeof Link> = (props: LinkProps) => {
    return <Link {...props} />
}

export const Default: Story = {
    render: BasicTemplate,
    args: {},
}

export const ToLink: Story = {
    render: BasicTemplate,

    args: {
        to: urls.projectHomepage(),
    },
}

export const DisabledWithReason: Story = {
    render: BasicTemplate,

    args: {
        disabledReason: 'Not allowed',
    },
}
