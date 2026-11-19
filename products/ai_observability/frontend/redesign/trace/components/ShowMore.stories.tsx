import type { Meta, StoryObj } from '@storybook/react'
import { within } from '@testing-library/dom'

import { userEvent } from 'storybook/test'

import { FIXTURE_LONG_ANSWER_MESSAGE, withWidth } from '../storyFixtures'
import { MessagePartView } from './MessagePartView'
import { ShowMore } from './ShowMore'

const meta: Meta<typeof ShowMore> = {
    title: 'Scenes-App/AI observability/Trace view/Show more',
    component: ShowMore,
    args: {
        children: FIXTURE_LONG_ANSWER_MESSAGE.parts.map((part, index) => <MessagePartView key={index} part={part} />),
    },
}
export default meta

type Story = StoryObj<typeof ShowMore>

export const Cut: Story = {}
export const CutNarrow: Story = { decorators: [withWidth(420)] }
export const Expanded: Story = {
    parameters: { testOptions: { snapshotBrowsers: [] } },
    play: async ({ canvasElement }) => {
        await userEvent.click(await within(canvasElement).findByText('Show more'))
    },
}
