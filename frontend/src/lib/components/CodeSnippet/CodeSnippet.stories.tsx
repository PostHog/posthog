import { Meta, StoryFn, StoryObj } from '@storybook/react'

import { CodeSnippet, CodeSnippetProps, Language } from './CodeSnippet'

type Story = StoryObj<typeof CodeSnippet>
const meta: Meta<typeof CodeSnippet> = {
    title: 'Lemon UI/Code Snippet',
    component: CodeSnippet,
    tags: ['autodocs'],
}
export default meta
const BasicTemplate: StoryFn<typeof CodeSnippet> = (props: CodeSnippetProps) => {
    return <CodeSnippet {...props} />
}

export const Default: Story = BasicTemplate.bind({})
Default.args = {
    children: 'I am some code',
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

export const JavaScript: Story = BasicTemplate.bind({})
JavaScript.args = {
    wrap: true,
    children: 'const helloWorld = 1 + 3;',
    language: Language.JavaScript,
}
