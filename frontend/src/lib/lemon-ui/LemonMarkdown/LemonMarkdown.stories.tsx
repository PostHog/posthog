import { Meta, StoryFn, StoryObj } from '@storybook/react'

import { LemonMarkdown as LemonMarkdownComponent, LemonMarkdownProps } from './LemonMarkdown'

type Story = StoryObj<typeof LemonMarkdownComponent>
const meta: Meta<typeof LemonMarkdownComponent> = {
    title: 'Lemon UI/Lemon Markdown',
    component: LemonMarkdownComponent,
    tags: ['autodocs'],
}
export default meta

const Template: StoryFn<typeof LemonMarkdownComponent> = (props: LemonMarkdownProps) => {
    return <LemonMarkdownComponent {...props} />
}

export const Default: Story = Template.bind({})
Default.args = {
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
}

export const LowKeyHeadings: Story = Template.bind({})
LowKeyHeadings.args = {
    children: `# Level 1
## Level 2

**Strong** and *emphasized* text.`,
    lowKeyHeadings: true,
}
