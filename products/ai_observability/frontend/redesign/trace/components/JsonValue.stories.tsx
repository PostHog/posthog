import type { Meta, StoryObj } from '@storybook/react'

import { withWidth } from '../storyFixtures'
import { JsonValue } from './JsonValue'

const meta: Meta<typeof JsonValue> = {
    title: 'Scenes-App/AI observability/Trace view/JSON value',
    component: JsonValue,
    parameters: { testOptions: { snapshotBrowsers: [] } },
    args: {
        value: {
            query: 'orders shipped this week',
            filters: { status: ['shipped', 'delivered'], region: 'EU' },
            limit: 50,
        },
    },
}
export default meta

type Story = StoryObj<typeof JsonValue>

export const Fields: Story = {}
export const FieldsNarrow: Story = { decorators: [withWidth(320)] }
export const Text: Story = { args: { value: 'The lookup returned no orders for this week.' } }
