import { Meta, StoryFn, StoryObj } from '@storybook/react'

import { CodeSnippet, CodeSnippetProps } from './CodeSnippet'

type Story = StoryObj<typeof CodeSnippet>
const meta: Meta<typeof CodeSnippet> = {
    title: 'Lemon UI/Code Snippet',
    component: CodeSnippet,
    tags: ['autodocs'],
    parameters: {
        testOptions: { include3000: true },
    },
}
export default meta
const BasicTemplate: StoryFn<typeof CodeSnippet> = (props: CodeSnippetProps) => {
    return <CodeSnippet {...props} />
}

export const Default: Story = BasicTemplate.bind({})
Default.args = {
    children: 'Click me',
}

export const Compact: Story = BasicTemplate.bind({})
Compact.args = {
    compact: true,
    children:
        'This is some really long text.This is some really long text.This is some really long text.This is some really long text.This is some really long text.This is some really long text.This is some really long text.This is some really long text.',
}

export const Wrap: Story = BasicTemplate.bind({})
Wrap.args = {
    wrap: true,
    children:
        'This is some really long text.This is some really long text.This is some really long text.This is some really long text.This is some really long text.This is some really long text.This is some really long text.This is some really long text.',
}
