import type { Meta, StoryObj } from '@storybook/react'

import { langchainCerebrasImageError } from '../sampleFixtures/langchainCerebrasImageError'
import { FIXTURE_GENERATION_PROPERTIES, FIXTURE_SPAN_PROPERTIES, FIXTURE_TREE } from '../storyFixtures'
import { NodePropertyList } from './NodePropertyList'

const meta: Meta<typeof NodePropertyList> = {
    title: 'Scenes-App/AI observability/Trace view/Node properties',
    component: NodePropertyList,
}
export default meta

type Story = StoryObj<typeof NodePropertyList>

const failedGeneration = langchainCerebrasImageError.tree[0].children[0].children[0]

export const Generation: Story = {
    args: { node: FIXTURE_TREE[0].children[1], properties: FIXTURE_GENERATION_PROPERTIES },
}
export const Span: Story = {
    args: { node: FIXTURE_TREE[0].children[0], properties: FIXTURE_SPAN_PROPERTIES },
}
export const SpanWithoutSessionOrPerson: Story = {
    args: {
        node: FIXTURE_TREE[0].children[0],
        properties: { ...FIXTURE_SPAN_PROPERTIES, sessionId: null, person: null },
    },
}
export const FailedGenerationWithUnknownStats: Story = {
    args: {
        node: failedGeneration,
        properties: langchainCerebrasImageError.details[failedGeneration.id].properties,
    },
}
