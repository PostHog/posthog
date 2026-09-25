import type { Meta, StoryObj } from '@storybook/react'

import { FIXTURE_TURN } from '../storyFixtures'
import { ThreadTurn } from './ThreadTurn'

const meta: Meta<typeof ThreadTurn> = {
    title: 'Scenes-App/AI observability/Trace view/Thread turn',
    component: ThreadTurn,
    args: { turn: FIXTURE_TURN, onSelectMessage: () => {} },
}
export default meta

export const Default: StoryObj<typeof ThreadTurn> = { args: { isActive: false } }
export const Active: StoryObj<typeof ThreadTurn> = { args: { isActive: true } }
