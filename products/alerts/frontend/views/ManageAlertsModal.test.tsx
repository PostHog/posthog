import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { Provider } from 'kea'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { createEmptyInsight } from 'scenes/insights/insightLogic'

import { InsightVizNode, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { InsightShortId } from '~/types'

import { ManageAlertsModal } from './ManageAlertsModal'

describe('ManageAlertsModal', () => {
    afterEach(() => {
        cleanup()
        jest.restoreAllMocks()
    })

    it('allows alert creation before feature flags arrive without recording experiment exposure', () => {
        jest.spyOn(posthog, 'onFeatureFlags').mockImplementation(() => () => {})
        initKeaTests()
        const capture = jest.spyOn(posthog, 'capture')
        const onCreateAlert = jest.fn()
        const insightShortId = 'alert-qa' as InsightShortId
        const query: InsightVizNode = {
            kind: NodeKind.InsightVizNode,
            source: { kind: NodeKind.TrendsQuery, series: [] },
        }

        render(
            <Provider>
                <ManageAlertsModal
                    isOpen
                    insightId={42}
                    insightShortId={insightShortId}
                    canCreateAlertForInsight
                    onCreateAlert={onCreateAlert}
                    insightLogicProps={{
                        dashboardItemId: insightShortId,
                        cachedInsight: {
                            ...createEmptyInsight(insightShortId),
                            id: 42,
                            alerts: [],
                            query,
                        },
                    }}
                />
            </Provider>
        )

        expect(featureFlagLogic.values.receivedFeatureFlags).toBe(false)
        expect(screen.getByText('There are no alerts for this insight')).toBeInTheDocument()
        const createButton = screen.getByText('New alert')
        expect(createButton.closest('button')).toBeEnabled()
        fireEvent.click(createButton)
        expect(onCreateAlert).toHaveBeenCalledTimes(1)
        expect(capture).not.toHaveBeenCalledWith(
            '$feature_flag_called',
            expect.objectContaining({ $feature_flag: FEATURE_FLAGS.INSIGHT_ALERTS_EMPTY_STATE_EXPERIMENT })
        )
    })
})
