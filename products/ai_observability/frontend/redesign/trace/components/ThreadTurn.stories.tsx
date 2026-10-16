import type { Meta, StoryObj } from '@storybook/react'

import { FIXTURE_ATTACHMENT_PARTS, FIXTURE_TURN } from '../storyFixtures'
import { ThreadTurn } from './ThreadTurn'

const meta: Meta<typeof ThreadTurn> = {
    title: 'Scenes-App/AI observability/Trace view/Thread turn',
    component: ThreadTurn,
    args: { turn: FIXTURE_TURN, onSelectMessage: () => {} },
}
export default meta

export const Default: StoryObj<typeof ThreadTurn> = { args: { isActive: false } }
export const Active: StoryObj<typeof ThreadTurn> = { args: { isActive: true } }
export const WithError: StoryObj<typeof ThreadTurn> = {
    args: {
        isActive: false,
        turn: {
            ...FIXTURE_TURN,
            messages: [
                {
                    id: 'm-user-image',
                    role: 'user',
                    parts: [{ kind: 'text', text: 'What does this chart show?' }, FIXTURE_ATTACHMENT_PARTS[0]],
                    isInternal: false,
                    sourceNodeId: 'gen-answer',
                },
            ],
            error: 'BadRequestError: 400 This model does not accept image input',
        },
    },
}
