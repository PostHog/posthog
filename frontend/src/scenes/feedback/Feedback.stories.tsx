import { ComponentMeta } from '@storybook/react'
import { Feedback, FeedbackInstructions } from './Feedback'

export default {
    title: 'Scenes-App/Feedback',
    component: Feedback,
    parameters: {
        testOptions: {
            waitForLoadersToDisappear: true,
        },
    },
} as ComponentMeta<typeof Feedback>

export const Instructions = (): JSX.Element => {
    return <FeedbackInstructions />
}
