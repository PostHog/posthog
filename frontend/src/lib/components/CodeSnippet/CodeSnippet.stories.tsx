import { Meta, StoryFn, StoryObj } from '@storybook/react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

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

export const CompactWithShortText: Story = BasicTemplate.bind({})
CompactWithShortText.args = {
    compact: true,
    children: 'This is not long text',
}

export const CompactWithLongText: Story = BasicTemplate.bind({})
CompactWithLongText.args = {
    compact: true,
    children:
        'This is some really long text.This is some really long text.This is some really long text.This is some really long text.This is some really long text.This is some really long text.This is some really long text.This is some really long text.',
}

export const WithoutWrapping: Story = BasicTemplate.bind({})
WithoutWrapping.args = {
    wrap: false,
    children:
        'This is some really long text.This is some really long text.This is some really long text.This is some really long text.This is some really long text.This is some really long text.This is some really long text.This is some really long text.',
}

export const WithoutWrappingWithAction: Story = BasicTemplate.bind({})
WithoutWrappingWithAction.args = {
    wrap: false,
    children:
        'This is some really long text.This is some really long text.This is some really long text.This is some really long text.This is some really long text.This is some really long text.This is some really long text.This is some really long text.',
    actions: (
        <>
            <LemonButton size="small" type="primary">
                one button
            </LemonButton>
            <LemonButton size="small" type="secondary">
                two button
            </LemonButton>
        </>
    ),
}

export const WithWrapping: Story = BasicTemplate.bind({})
WithWrapping.args = {
    wrap: true,
    children:
        'This is some really long text.This is some really long text.This is some really long text.This is some really long text.This is some really long text.This is some really long text.This is some really long text.This is some really long text.',
}

export const WithWrappingAndAction: Story = BasicTemplate.bind({})
WithWrappingAndAction.args = {
    wrap: true,
    children:
        'This is some really long text.This is some really long text.This is some really long text.This is some really long text.This is some really long text.This is some really long text.This is some really long text.This is some really long text.',
    actions: (
        <>
            <LemonButton size="small" type="primary">
                one button
            </LemonButton>
            <LemonButton size="small" type="secondary">
                two button
            </LemonButton>
        </>
    ),
}

export const JavaScript: Story = BasicTemplate.bind({})
JavaScript.args = {
    wrap: true,
    children: 'const helloWorld = 1 + 3;',
    language: Language.JavaScript,
}
