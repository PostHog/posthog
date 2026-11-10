import type { Meta, StoryObj } from '@storybook/react'

import { createDraft } from './scoreDefinitionModalUtils'
import { ScorerSummary } from './ScorerSummary'

const meta: Meta<typeof ScorerSummary> = {
    title: 'AI observability/Scorer summary',
    component: ScorerSummary,
    parameters: { testOptions: { snapshotBrowsers: [] } },
    args: {
        draft: {
            ...createDraft('create'),
            name: 'Ready to send',
            calculation: 'composite',
            kind: 'boolean',
            expression: '(safe) and (accurate)',
        },
    },
}
export default meta
type Story = StoryObj<typeof meta>
export const BooleanComposite: Story = {}
export const Categorical: Story = {
    args: {
        draft: {
            ...createDraft('create'),
            name: 'Review decision',
            calculation: 'composite',
            kind: 'categorical',
            expression: '"good" if safe and accurate else "bad"',
        },
    },
}
export const NestedFormula: Story = {
    args: {
        draft: {
            ...createDraft('create'),
            name: 'Relevant answer',
            calculation: 'composite',
            expression: '(("excellent" in score1) and not ("partial" in score1 or "off_topic" in score1))',
        },
    },
}
export const Numeric: Story = {
    args: {
        draft: {
            ...createDraft('create'),
            name: 'Accuracy',
            kind: 'numeric',
            numericMin: '0',
            numericMax: '1',
            numericPassingEnabled: true,
            numericPassingThreshold: '0.8',
        },
    },
}
