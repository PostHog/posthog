import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { ScoreDefinitionForm, type ScoreDefinitionFormProps } from './ScoreDefinitionForm'
import { createDraft } from './scoreDefinitionModalUtils'

const meta: Meta<typeof ScoreDefinitionForm> = {
    title: 'AI observability/Scorer form',
    component: ScoreDefinitionForm,
    parameters: { layout: 'padded' },
    args: {
        isNew: false,
        disabled: false,
        draft: {
            ...createDraft('create'),
            name: 'Answer quality',
            kind: 'numeric',
            numericMin: '0',
            numericMax: '10',
            numericPassingEnabled: true,
            numericPassingThreshold: '7',
        },
    },
    render: function Render(args): JSX.Element {
        const [draft, setDraft] = useState(args.draft)
        return (
            <div className="w-[768px] max-w-full">
                <ScoreDefinitionForm
                    {...args}
                    draft={draft}
                    setDraftField={(field, value) => setDraft((current) => ({ ...current, [field]: value }))}
                    updateOptionLabel={(index, label) =>
                        setDraft((current) => ({
                            ...current,
                            options: current.options.map((option, i) => (i === index ? { ...option, label } : option)),
                        }))
                    }
                    addOption={() =>
                        setDraft((current) => ({ ...current, options: [...current.options, { key: '', label: '' }] }))
                    }
                    removeOption={(index) =>
                        setDraft((current) => ({
                            ...current,
                            options: current.options.filter((_, i) => i !== index),
                        }))
                    }
                />
            </div>
        )
    },
}

export default meta
type Story = StoryObj<ScoreDefinitionFormProps>

export const Numeric: Story = {}
export const NewScorer: Story = { args: { isNew: true, draft: createDraft('create') } }
export const BooleanDetector: Story = {
    args: {
        draft: {
            ...createDraft('create'),
            name: 'Hallucination',
            kind: 'boolean',
            trueLabel: 'Flagged',
            falseLabel: 'Clear',
            booleanPassing: 'false',
        },
    },
}
export const Narrow: Story = {
    decorators: [
        (Story) => (
            <div className="w-[520px]">
                <Story />
            </div>
        ),
    ],
}
