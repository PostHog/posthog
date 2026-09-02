import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { MetricMarkdownEditor, MetricMarkdownEditorProps } from './MetricMarkdownEditor'

type Story = StoryObj<MetricMarkdownEditorProps>

const meta: Meta<MetricMarkdownEditorProps> = {
    title: 'Components/Markdown editor/Metric definition',
    component: MetricMarkdownEditor,
    tags: ['autodocs'],
    render: (props) => {
        const [value, setValue] = useState(props.value ?? '')
        return <MetricMarkdownEditor {...props} value={value} onChange={setValue} />
    },
}

export default meta

export const Default: Story = {
    args: {
        value: '1. Sum `amount` for the current month\n\n```sql\nSELECT sum(amount) FROM payments\n```',
    },
}

export const LegacyFallbackForUnsafeMarkdown: Story = {
    args: {
        value: 'This definition embeds an image, which the rich editor would drop: ![chart](https://example.com/chart.png)',
    },
}
