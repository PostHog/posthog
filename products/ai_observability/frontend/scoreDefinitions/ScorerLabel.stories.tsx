import type { Meta, StoryObj } from '@storybook/react'

import { ScorerLabel } from './ScorerLabel'

const meta: Meta<typeof ScorerLabel> = {
    title: 'AI observability/Scorer label',
    component: ScorerLabel,
    decorators: [
        (Story) => (
            <div className="w-40">
                <Story />
            </div>
        ),
    ],
    args: {
        scorer: {
            name: 'Checks whether the answer is supported by the supplied reference material',
            short_name: 'Groundedness',
            version: 12,
        },
    },
}
export default meta
type Story = StoryObj<typeof ScorerLabel>

export const ShortName: Story = {}
export const FullNameFallback: Story = {
    args: { scorer: { ...meta.args!.scorer!, short_name: '' } },
}
export const LongWord: Story = {
    args: {
        scorer: { name: 'Reference consistency', short_name: 'ReferenceMaterialConsistencyVerification', version: 1 },
    },
}
