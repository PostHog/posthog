import type { Meta, StoryObj } from '@storybook/react'

import { ErrorCallout } from './ErrorCallout'

const meta: Meta<typeof ErrorCallout> = {
    title: 'Scenes-App/AI observability/Trace view/Error callout',
    component: ErrorCallout,
}
export default meta

export const Default: StoryObj<typeof ErrorCallout> = {
    args: { message: 'RateLimitError: 429 Too Many Requests, retry after 12s' },
}
