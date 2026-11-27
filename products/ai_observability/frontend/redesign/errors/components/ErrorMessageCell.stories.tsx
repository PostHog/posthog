import type { Meta, StoryObj } from '@storybook/react'

import { withWidth } from '../../trace/storyFixtures'
import { ErrorMessageCell } from './ErrorMessageCell'

const meta: Meta<typeof ErrorMessageCell> = {
    title: 'Scenes-App/AI observability/Errors/Error message cell',
    component: ErrorMessageCell,
    parameters: { testOptions: { snapshotBrowsers: [] } },
    args: { message: 'TimeoutError: the example-model call took longer than 30 seconds', onOpen: () => {} },
    decorators: [withWidth(360)],
}
export default meta

type Story = StoryObj<typeof ErrorMessageCell>

export const Short: Story = {}

export const ClampedToTwoLines: Story = {
    args: {
        message:
            'BadRequestError: the example-model deployment rejected the request because the messages field held a tool result with no matching tool call, and the request id was req_example_0001',
    },
}

export const UnbrokenToken: Story = {
    args: { message: 'ValidationError: field_one.field_two.field_three.field_four.field_five.field_six.field_seven' },
}
