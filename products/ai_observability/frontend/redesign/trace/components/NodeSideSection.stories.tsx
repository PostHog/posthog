import type { Meta, StoryObj } from '@storybook/react'

import { FIXTURE_GENERATION_INPUT, withWidth } from '../storyFixtures'
import { NodeSideSection } from './NodeSideSection'

const meta: Meta<typeof NodeSideSection> = {
    title: 'Scenes-App/AI observability/Trace view/Input and output',
    component: NodeSideSection,
    args: { title: 'Input', emptyText: 'No input captured.', openFrom: 0 },
}
export default meta

type Story = StoryObj<typeof NodeSideSection>

const value = { question: 'Why did my invoice go up this month?', account_id: 'acct_42' }

export const KeyValues: Story = { args: { side: { kind: 'json', value } } }
export const PlainText: Story = { args: { side: { kind: 'json', value: 'Why did my invoice go up?' } } }
export const NothingCaptured: Story = { args: { side: { kind: 'json', value: null } } }
export const EmptyObject: Story = { args: { side: { kind: 'json', value: {} } } }
export const Messages: Story = { args: { side: { kind: 'messages', messages: FIXTURE_GENERATION_INPUT } } }
export const NoMessages: Story = { args: { side: { kind: 'messages', messages: [] } } }
export const Narrow: Story = { args: { side: { kind: 'json', value } }, decorators: [withWidth(380)] }
