import type { Meta, StoryObj } from '@storybook/react'

import { LemonMarkdown as LemonMarkdownComponent, LemonMarkdownProps } from './LemonMarkdown'

type Story = StoryObj<LemonMarkdownProps>
const meta: Meta<LemonMarkdownProps> = {
    title: 'Lemon UI/Lemon Markdown',
    component: LemonMarkdownComponent,
    tags: ['autodocs'],
}
export default meta

export const Default: Story = {
    args: {
        children: `# Lorem ipsum

## Linguae despexitque sine sua tibi

Lorem markdownum et, dant officio siquid indigenae. Spectatrix contigit tellus, sum [summos](http://sim.org/sit), suis.

- Quattuor creditur
- Veniebat patriaeque cavatur
- En anguem tamen

\`\`\`python
print("X")
\`\`\`

---

1. Quattuor creditur
2. Veniebat patriaeque cavatu
3. En anguem tamen`,
    },
}

export const LowKeyHeadings: Story = {
    args: {
        children: `# Level 1
## Level 2

**Strong** and *emphasized* text.`,
        lowKeyHeadings: true,
    },
}

export const WithTables: Story = {
    args: {
        children: `# Analytics dashboard

Here's a breakdown of our top traffic sources:

| Source | Unique users | Percentage |
|--------|-------------|------------|
| Direct | 362,389 | 45.2% |
| Google | 122,910 | 15.3% |
| posthog.com | 23,067 | 2.9% |
| us.posthog.com | 21,593 | 2.7% |
| eu.posthog.com | 10,723 | 1.3% |
| LinkedIn | 5,255 | 0.7% |
| GitHub | 4,019 | 0.5% |
| Bing | 2,950 | 0.4% |
| DuckDuckGo | 2,933 | 0.4% |

## Browser breakdown

| Browser | Users | Market share |
|---------|-------|-------------|
| Chrome | 450,123 | 72.1% |
| Safari | 89,234 | 14.3% |
| Firefox | 45,678 | 7.3% |
| Edge | 25,432 | 4.1% |
| Other | 13,890 | 2.2% |

*Data from the last 30 days*`,
    },
}

export const GitHubFlavoredMarkdown: Story = {
    args: {
        children: `# GitHub-flavored Markdown features

## Strikethrough text
This text is ~~deleted~~ and this text is **bold**.

You can also combine ~~**bold and deleted**~~ text.

## Task lists
Here's our development progress:

- [x] Add remark-gfm plugin support
- [x] Implement table styling
- [x] Create Storybook stories
- [ ] Add comprehensive documentation
- [ ] Performance optimization
- [ ] Mobile responsiveness testing

## Autolink literals
Visit https://posthog.com for more information about our product.

You can also check out our GitHub repository at https://github.com/PostHog/posthog

Email us at hello@posthog.com for support.`,
    },
}

export const Strikethrough: Story = {
    args: {
        children: `# Text Formatting

This is ~~incorrect~~ **correct** information.

~~The old way~~ → The new way

You can combine ~~strikethrough~~ with *emphasis* and **bold** text.`,
    },
}

export const TaskLists: Story = {
    args: {
        children: `# Project Todo List

## Sprint 1
- [x] Setup project repository
- [x] Configure CI/CD pipeline
- [x] Write initial documentation
- [ ] Implement core features
- [ ] Add comprehensive tests

## Sprint 2
- [ ] Performance optimization
- [ ] Security audit
- [ ] User acceptance testing
- [x] Code review process

## Notes
- Use [x] for completed tasks
- Use [ ] for pending tasks
- Tasks can be nested and combined with other markdown`,
    },
}

export const AutolinkLiterals: Story = {
    args: {
        children: `# Automatic Links

## Websites
Visit https://posthog.com to learn more about our platform.

Check out our documentation at https://posthog.com/docs

## Email Addresses
Contact us at hello@posthog.com for general inquiries.

For technical support: support@posthog.com

## Mixed Content
Our GitHub repository (https://github.com/PostHog/posthog) contains the full source code.

For questions, email team@posthog.com or visit https://posthog.com/questions`,
    },
}
