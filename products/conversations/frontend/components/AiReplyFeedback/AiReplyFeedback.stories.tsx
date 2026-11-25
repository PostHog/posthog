import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import type { AiReplyFeedbackRating } from '../../types'
import { AiReplyFeedback } from './AiReplyFeedback'

const meta: Meta<typeof AiReplyFeedback> = {
    title: 'Scenes-App/Support/AI reply feedback',
    component: AiReplyFeedback,
    parameters: { testOptions: { snapshotBrowsers: [] } },
}
export default meta

type Story = StoryObj<typeof AiReplyFeedback>

function StatefulFeedback({ initialRating }: { initialRating: AiReplyFeedbackRating | null }): JSX.Element {
    const [rating, setRating] = useState<AiReplyFeedbackRating | null>(initialRating)
    return <AiReplyFeedback rating={rating} onSubmit={setRating} />
}

export const Unrated: Story = { render: () => <StatefulFeedback initialRating={null} /> }

export const RatedUseful: Story = { render: () => <StatefulFeedback initialRating="good" /> }
