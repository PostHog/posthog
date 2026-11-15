import { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { TemplateVariableTextArea } from './TemplateVariableTextArea'

const meta: Meta<typeof TemplateVariableTextArea> = {
    title: 'Components/Template Variable Text Area',
    component: TemplateVariableTextArea,
    parameters: {
        docs: {
            description: {
                component:
                    'The AI playground prompt editor. `{{variables}}` with a value render in the accent color, unfilled ones in the warning color. The highlight comes from a backdrop div behind a transparent textarea, so typing must keep the caret exactly on the glyphs.',
            },
        },
    },
}
export default meta
type Story = StoryObj<typeof TemplateVariableTextArea>

export const FilledAndUnfilledVariables: Story = {
    render: function Render() {
        const [value, setValue] = useState(
            'You are a helpful assistant for {{company}}.\n' +
                'Answer every question about {{topic}} in a {{tone}} tone. ' +
                'A long line should wrap identically in both layers, so the caret stays on the glyphs even after wrapping. ' +
                'Literal braces like {{ spaced }} and {{}} stay plain.\n' +
                // An unbroken token must break at the same point in both layers
                'data:application/x-unbroken-token;aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
        )
        return (
            <div className="max-w-200">
                <TemplateVariableTextArea value={value} onChange={setValue} unfilledVariables={['tone']} minRows={2} />
            </div>
        )
    },
}

export const EmptyWithPlaceholder: Story = {
    render: function Render() {
        const [value, setValue] = useState('')
        return (
            <div className="max-w-200">
                <TemplateVariableTextArea
                    value={value}
                    onChange={setValue}
                    unfilledVariables={[]}
                    placeholder="System instructions for the AI assistant..."
                    minRows={2}
                />
            </div>
        )
    },
}
