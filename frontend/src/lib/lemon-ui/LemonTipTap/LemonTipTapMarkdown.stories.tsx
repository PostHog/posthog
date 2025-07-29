import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { LemonTipTapMarkdown } from './LemonTipTapMarkdown'

const meta: Meta<typeof LemonTipTapMarkdown> = {
    title: 'Lemon UI/Lemon TipTap Markdown',
    component: LemonTipTapMarkdown,
    parameters: {
        testOptions: {
            waitForSelector: '.LemonTextMarkdown',
        },
    },
    tags: ['autodocs'],
}

export default meta
type Story = StoryObj<typeof meta>

const Template: StoryFn<typeof LemonTipTapMarkdown> = (props: LemonTipTapMarkdownProps) => {
    const [value, setValue] = useState(props.value || '')
    return <LemonTipTapMarkdown {...props} value={value} onChange={setValue} />
}

export const Empty: Story = {
    render: Template,
    args: {
        value: '',
        placeholder: 'Start typing your markdown...',
    },
}

export const WithContent: Story = {
    render: Template,
    args: {
        value: `# Hello World

This is a **bold** and *italic* text example.

## Features

- Rich text editing with TipTap
- Markdown shortcuts
- Image upload support
- Emoji picker

### Code Example

\`\`\`javascript
function hello() {
    console.log("Hello, world!");
}
\`\`\`

> This is a blockquote with some important information.

[Link to PostHog](https://posthog.com)`,
        placeholder: 'Start typing your markdown...',
    },
}

export const WithMaxLength: Story = {
    render: Template,
    args: {
        value: 'Short text',
        maxLength: 50,
        placeholder: 'Type here (max 50 characters)...',
    },
}

export const WithMaxLengthExceeded: Story = {
    render: Template,
    args: {
        value: 'This text is way too long and exceeds the maximum character limit that was set for this field',
        maxLength: 50,
        placeholder: 'Type here (max 50 characters)...',
    },
}

export const MinimalHeight: Story = {
    render: Template,
    args: {
        value: '',
        minRows: 3,
        placeholder: 'Minimal height example...',
    },
}
