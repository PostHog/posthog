import type { Meta, StoryObj } from '@storybook/react'

import { SentenceList, SentenceListProps } from './SentenceList'

type Story = StoryObj<SentenceListProps>
const meta: Meta<SentenceListProps> = {
    title: 'Components/SentenceList',
    component: SentenceList,
    parameters: {},
}
export default meta

export const FullSentence: Story = {
    args: {
        prefix: 'Bob',
        suffix: 'on feature flag cool-flag',
        listParts: [
            'changed description to "something cool"',
            'changed name to "woop"',
            'changed rollout percentage to 52%',
        ],
    },
}

export const OneAction: Story = {
    args: { listParts: ['changed description to "something cool"'] },
}

export const TwoActions: Story = {
    args: { listParts: ['changed description to "something cool"', 'changed name to "woop"'] },
}

export const ThreeActions: Story = {
    args: {
        listParts: [
            'changed description to "something cool"',
            'changed name to "woop"',
            'changed rollout percentage to 52%',
        ],
    },
}
