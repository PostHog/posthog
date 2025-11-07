import { Meta, StoryFn, StoryObj } from '@storybook/react'

import { urls } from 'scenes/urls'

import { Link, LinkProps } from './Link'

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

export const Default: Story = BasicTemplate.bind({})
Default.args = {}

export const ToLink: Story = BasicTemplate.bind({})
ToLink.args = {
    to: urls.projectHomepage(),
    children: 'Click me (or side click for browser like menu)',
}

export const DisabledWithReason: Story = BasicTemplate.bind({})
DisabledWithReason.args = {
    disabledReason: 'Not allowed',
}
