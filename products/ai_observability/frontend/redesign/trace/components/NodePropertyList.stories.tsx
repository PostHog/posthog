import type { Meta, StoryObj } from '@storybook/react'

import type { TraceNodeDetailApi } from '../../../generated/api.schemas'
import { langchainCerebrasImageError } from '../sampleFixtures/langchainCerebrasImageError'
import { SampleNodeDetail } from '../sampleFixtures/sampleTraceFixture'
import { FIXTURE_TRACE, FIXTURE_TREE } from '../storyFixtures'
import { NodePropertyList } from './NodePropertyList'

const meta: Meta<typeof NodePropertyList> = {
    title: 'Scenes-App/AI observability/Trace view/Node properties',
    component: NodePropertyList,
}
export default meta

type Story = StoryObj<typeof NodePropertyList>

function readNode({ load }: SampleNodeDetail): TraceNodeDetailApi | null {
    return load.status === 'ready' ? load.node : null
}

const generation = FIXTURE_TREE[0].children[1]
const span = FIXTURE_TREE[0].children[0]
const spanDetail = readNode(FIXTURE_TRACE.details[span.id])
const failedGeneration = langchainCerebrasImageError.tree[0].children[0].children[0]

export const Generation: Story = {
    args: { node: generation, detail: readNode(FIXTURE_TRACE.details[generation.id]), trace: FIXTURE_TRACE.trace },
}
export const Span: Story = {
    args: { node: span, detail: spanDetail, trace: FIXTURE_TRACE.trace },
}
export const SpanWithoutSessionOrPerson: Story = {
    args: {
        node: span,
        detail: spanDetail && { ...spanDetail, metadata: { ...spanDetail.metadata, sessionId: null } },
        trace: { ...FIXTURE_TRACE.trace, person: null },
    },
}
export const FailedGenerationWithUnknownStats: Story = {
    args: {
        node: failedGeneration,
        detail: readNode(langchainCerebrasImageError.details[failedGeneration.id]),
        trace: langchainCerebrasImageError.trace,
    },
}
