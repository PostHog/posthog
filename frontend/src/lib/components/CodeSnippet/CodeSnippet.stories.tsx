import type { Meta, StoryObj } from '@storybook/react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { CodeSnippet, CodeSnippetProps, Language } from './CodeSnippet'

type Story = StoryObj<CodeSnippetProps>
const meta: Meta<CodeSnippetProps> = {
    title: 'Lemon UI/Code Snippet',
    component: CodeSnippet,
    tags: ['autodocs'],
}
export default meta

export const Default: Story = {
    args: {
        children: 'I am some code',
    },
}

export const CompactWithShortText: Story = {
    args: {
        compact: true,
        children: 'This is not long text',
    },
}

export const CompactWithLongText: Story = {
    args: {
        compact: true,
        children:
            'This is some really long text.This is some really long text.This is some really long text.This is some really long text.This is some really long text.This is some really long text.This is some really long text.This is some really long text.',
    },
}

export const WithoutWrapping: Story = {
    args: {
        wrap: false,
        children:
            'This is some really long text.This is some really long text.This is some really long text.This is some really long text.This is some really long text.This is some really long text.This is some really long text.This is some really long text.',
    },
}

export const WithoutWrappingWithAction: Story = {
    args: {
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
    },
}

export const WithWrapping: Story = {
    args: {
        wrap: true,
        children:
            'This is some really long text.This is some really long text.This is some really long text.This is some really long text.This is some really long text.This is some really long text.This is some really long text.This is some really long text.',
    },
}

export const WithWrappingAndAction: Story = {
    args: {
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
    },
}

export const JavaScript: Story = {
    args: {
        wrap: true,
        children: 'const helloWorld = 1 + 3;',
        language: Language.JavaScript,
    },
}
