import type { Meta, StoryObj } from '@storybook/react'

import { fn } from 'storybook/test'

import { RelatedEmojiButtons } from './RelatedEmojiButtons'

const meta: Meta<typeof RelatedEmojiButtons> = {
    title: 'Lemon UI/Emoji Picker Related Results',
    component: RelatedEmojiButtons,
    args: {
        suggestions: [
            { emoji: '🦖', label: 'T-Rex' },
            { emoji: '🦕', label: 'sauropod' },
            { emoji: '🎢', label: 'roller coaster' },
            { emoji: '🎡', label: 'ferris wheel' },
        ],
        onEmojiSelect: fn(),
    },
}

export default meta

export const JurassicPark: StoryObj<typeof RelatedEmojiButtons> = {}
