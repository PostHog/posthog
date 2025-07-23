import type { Meta, StoryObj } from '@storybook/react'

import { LemonTipTap } from './LemonTipTap'

const meta: Meta<typeof LemonTipTap> = {
    title: 'Lemon UI/Lemon TipTap',
    component: LemonTipTap,
    parameters: {
        testOptions: {
            waitForSelector: '.LemonTipTap',
        },
    },
    tags: ['autodocs'],
}

export default meta
type Story = StoryObj<typeof meta>

const basicMarkdown = `# Hello World

This is a **bold** and *italic* text example.

- First item
- Second item
- Third item

## Code Example

Here's some code:

\`\`\`javascript
function hello() {
    console.log("Hello, world!");
}
\`\`\`

[Link to PostHog](https://posthog.com)

> This is a blockquote
> 
> It can span multiple lines

1. Numbered list
2. Second item
3. Third item

---

Final paragraph with some \`inline code\`.`

export const Basic: Story = {
    args: {
        children: basicMarkdown,
    },
}

export const LowKeyHeadings: Story = {
    args: {
        children: basicMarkdown,
        lowKeyHeadings: true,
    },
}

export const ShortText: Story = {
    args: {
        children: 'Just a **simple** markdown text with *emphasis*.',
    },
}

export const CodeWrapping: Story = {
    args: {
        children:
            '```javascript\nconst veryLongVariableName = "This is a very long line of code that should wrap when wrapCode is enabled";\n```',
        wrapCode: true,
    },
}

export const Lists: Story = {
    args: {
        children: `## Todo List

- [x] Completed task
- [ ] Incomplete task
- [ ] Another incomplete task

## Regular Lists

1. First item
2. Second item
   - Nested item
   - Another nested item
3. Third item`,
    },
}
