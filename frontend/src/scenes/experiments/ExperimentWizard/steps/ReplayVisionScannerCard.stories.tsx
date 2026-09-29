import type { Meta, StoryObj } from '@storybook/react'

import { DEFAULT_MODEL, OBSERVATION_CREDITS_BY_MODEL } from 'products/replay_vision/frontend/replay_scanners/types'
import { formatCredits } from 'products/replay_vision/frontend/utils/credits'

import { ReplayVisionScannerCard } from './ReplayVisionScannerCard'

const meta: Meta<typeof ReplayVisionScannerCard> = {
    title: 'Experiments/ReplayVisionScannerCard',
    component: ReplayVisionScannerCard,
    args: {
        onChange: () => {},
        sessionPrice: formatCredits(OBSERVATION_CREDITS_BY_MODEL[DEFAULT_MODEL]),
    },
}
export default meta

type Story = StoryObj<typeof ReplayVisionScannerCard>

export const Off: Story = {
    args: { checked: false },
}

export const On: Story = {
    args: { checked: true },
}
