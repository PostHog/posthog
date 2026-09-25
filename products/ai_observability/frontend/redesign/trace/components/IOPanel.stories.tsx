import type { Meta, StoryObj } from '@storybook/react'

import { withWidth } from '../storyFixtures'
import { IOPanel } from './IOPanel'

const meta: Meta<typeof IOPanel> = {
    title: 'Scenes-App/AI observability/Trace view/Input and output',
    component: IOPanel,
}
export default meta

type Story = StoryObj<typeof IOPanel>

const input = { question: 'Why did my invoice go up this month?', account_id: 'acct_42' }
const output = { answer: 'Your team added two seats on August 12.', sources: ['help-seats', 'help-proration'] }

export const KeyValues: Story = { args: { input, output } }
export const PlainText: Story = { args: { input: 'Why did my invoice go up?', output: 'Two seats were added.' } }
export const NothingCaptured: Story = { args: { input: null, output: undefined } }
export const EmptyObject: Story = { args: { input: {}, output: 'Two seats were added.' } }
export const Narrow: Story = { args: { input, output }, decorators: [withWidth(380)] }
