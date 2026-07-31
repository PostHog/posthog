import '@testing-library/jest-dom'

import { cleanup, render, waitFor } from '@testing-library/react'
import { BindLogic, Provider } from 'kea'

import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { useMocks } from '~/mocks/jest'
import { FunnelsQuery, NodeKind, TrendsQuery } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { InsightShortId } from '~/types'

import type { IsoDayOfWeek } from './daysOfWeekFilterUtils'
import { InsightQuillDateFilter } from './InsightQuillDateFilter'

const Insight123 = '123' as InsightShortId
const insightProps = { dashboardItemId: Insight123 }

function makeTrendsQuery(daysOfWeek: IsoDayOfWeek[] | null = null): TrendsQuery {
    return {
        kind: NodeKind.TrendsQuery,
        series: [{ kind: NodeKind.EventsNode, name: '$pageview', event: '$pageview' }],
        dateRange: { date_from: '-7d', daysOfWeek },
    }
}

function makeFunnelsStepsQuery(daysOfWeek: IsoDayOfWeek[] | null = null): FunnelsQuery {
    return {
        kind: NodeKind.FunnelsQuery,
        series: [{ kind: NodeKind.EventsNode, name: '$pageview', event: '$pageview' }],
        dateRange: { date_from: '-7d', daysOfWeek },
    }
}

describe('InsightQuillDateFilter', () => {
    let vizDataLogic: ReturnType<typeof insightVizDataLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/insights/trend': [],
                '/api/environments/:team_id/insights/': { results: [{}] },
            },
        })
        initKeaTests()

        insightLogic(insightProps).mount()
        insightDataLogic(insightProps).mount()
        vizDataLogic = insightVizDataLogic(insightProps)
        vizDataLogic.mount()
    })

    afterEach(() => {
        cleanup()
    })

    function setupAndRender(query: TrendsQuery | FunnelsQuery): void {
        vizDataLogic.actions.updateQuerySource(query)

        render(
            <Provider>
                <BindLogic logic={insightLogic} props={insightProps}>
                    <InsightQuillDateFilter disabled={false} />
                </BindLogic>
            </Provider>
        )
    }

    it('clears daysOfWeek when the insight changes to a kind that does not support it', async () => {
        setupAndRender(makeTrendsQuery([1, 2, 3, 4, 5]))
        expect(vizDataLogic.values.dateRange?.daysOfWeek).toEqual([1, 2, 3, 4, 5])

        vizDataLogic.actions.updateQuerySource(makeFunnelsStepsQuery([1, 2, 3, 4, 5]))

        await waitFor(() => {
            expect(vizDataLogic.values.dateRange?.daysOfWeek ?? null).toBeNull()
        })
    })

    it('leaves daysOfWeek untouched while the query kind keeps support for it', async () => {
        setupAndRender(makeTrendsQuery([1, 2, 3, 4, 5]))

        vizDataLogic.actions.updateQuerySource(makeTrendsQuery([1, 2, 3, 4, 5]))

        await waitFor(() => {
            expect(vizDataLogic.values.dateRange?.daysOfWeek).toEqual([1, 2, 3, 4, 5])
        })
    })
})
