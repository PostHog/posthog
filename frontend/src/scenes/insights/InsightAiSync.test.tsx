import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
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

    it('registers completed apply-back for the saved insight and renders the conflict choice', () => {
        const sceneLogic = insightLogic(insightLogicProps)
        const syncLogic = insightAiSyncLogic({ insightLogicProps })
        sceneLogic.mount()
        syncLogic.mount()
        syncLogic.actions.setPendingAiConflict()

        render(
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
        expect(screen.getByText('PostHog AI updated this insight')).toBeInTheDocument()
        expect(screen.getByText(/You have unsaved changes/)).toBeInTheDocument()
        expect(screen.getByText('Keep my changes')).toBeInTheDocument()
        expect(screen.getByText('Use AI changes')).toBeInTheDocument()

        syncLogic.unmount()
        sceneLogic.unmount()
    })
})
