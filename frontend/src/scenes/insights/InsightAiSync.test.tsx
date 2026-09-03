import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { BindLogic } from 'kea'

import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { InsightLogicProps, InsightShortId, QueryBasedInsightModel } from '~/types'

import { useMcpToolApplyBack } from 'products/posthog_ai/frontend/api/logics'

import { InsightAiSync } from './InsightAiSync'
import { INSIGHT_AI_TOOL_NAMES, insightAiSyncLogic } from './insightAiSyncLogic'
import { insightLogic } from './insightLogic'

jest.mock('products/posthog_ai/frontend/api/logics', () => ({
    useMcpToolApplyBack: jest.fn(),
}))

const insightLogicProps: InsightLogicProps = {
    dashboardItemId: 'abc123' as InsightShortId,
    cachedInsight: {
        id: 42,
        short_id: 'abc123',
        saved: true,
        name: 'Saved insight',
        query: {
            kind: NodeKind.InsightVizNode,
            source: {
                kind: NodeKind.TrendsQuery,
                series: [{ kind: NodeKind.EventsNode, event: '$pageview', math: 'total' }],
            },
        },
    } as unknown as QueryBasedInsightModel,
}

describe('InsightAiSync', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
        jest.clearAllMocks()
    })

    it('registers completed apply-back, forwards its completion, and renders the conflict choice', () => {
        const sceneLogic = insightLogic(insightLogicProps)
        const syncLogic = insightAiSyncLogic({ insightLogicProps })
        const agentToolCompleted = jest.spyOn(syncLogic.actions, 'agentToolCompleted')
        sceneLogic.mount()
        syncLogic.mount()
        act(() => syncLogic.actions.setPendingAiConflict())

        const { container } = render(
            <BindLogic logic={insightLogic} props={insightLogicProps}>
                <InsightAiSync insightLogicProps={insightLogicProps} />
            </BindLogic>
        )

        const applyBackOptions = jest.mocked(useMcpToolApplyBack).mock.calls[0][0]
        expect(applyBackOptions).toMatchObject({
            tools: INSIGHT_AI_TOOL_NAMES,
            targetKey: 'insight:abc123',
            active: true,
            applyOn: 'tool_call_completed',
        })
        applyBackOptions.onApply({ toolName: 'insight-update' } as never, { innerInput: { id: 99 } })
        expect(agentToolCompleted).toHaveBeenCalledWith('insight-update', { id: 99 })
        expect(screen.getByText('PostHog AI updated this insight')).toBeInTheDocument()
        expect(screen.getByText(/You have unsaved changes/)).toBeInTheDocument()
        expect(screen.getByText('Keep my changes')).toBeInTheDocument()
        expect(screen.getByText('Use AI changes')).toBeInTheDocument()
        expect(container.querySelector('[data-attr="insight-ai-keep-changes"]')).not.toBeNull()
        expect(container.querySelector('[data-attr="insight-ai-use-ai-changes"]')).not.toBeNull()

        fireEvent.click(container.querySelector('[data-attr="insight-ai-keep-changes"]')!)
        expect(syncLogic.values.hasPendingAiConflict).toBe(false)

        act(() => syncLogic.actions.setPendingAiConflict())
        fireEvent.click(container.querySelector('[data-attr="insight-ai-use-ai-changes"]')!)
        expect(syncLogic.values.isApplyingAiChanges).toBe(true)
        expect(container.querySelector('[data-attr="insight-ai-keep-changes"]')).toHaveAttribute(
            'aria-disabled',
            'true'
        )
        expect(container.querySelector('[data-attr="insight-ai-use-ai-changes"]')).toHaveAttribute(
            'aria-disabled',
            'true'
        )

        syncLogic.unmount()
        sceneLogic.unmount()
    })

    it('registers an inactive unloaded target without applying it', () => {
        const unloadedInsightLogicProps: InsightLogicProps = { dashboardItemId: 'new' }
        const sceneLogic = insightLogic(unloadedInsightLogicProps)
        const syncLogic = insightAiSyncLogic({ insightLogicProps: unloadedInsightLogicProps })
        sceneLogic.mount()
        syncLogic.mount()

        render(
            <BindLogic logic={insightLogic} props={unloadedInsightLogicProps}>
                <InsightAiSync insightLogicProps={unloadedInsightLogicProps} />
            </BindLogic>
        )

        expect(jest.mocked(useMcpToolApplyBack).mock.calls[0][0]).toMatchObject({
            targetKey: 'insight:unloaded',
            active: false,
        })

        syncLogic.unmount()
        sceneLogic.unmount()
    })
})
