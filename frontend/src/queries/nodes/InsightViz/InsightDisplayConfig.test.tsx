import '@testing-library/jest-dom'

import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BindLogic, Provider } from 'kea'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { useMocks } from '~/mocks/jest'
import { NodeKind, TrendsQuery } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { BaseMathType, ChartDisplayType, InsightShortId } from '~/types'

import { InsightDisplayConfig } from './InsightDisplayConfig'

const Insight123 = '123' as InsightShortId
const insightProps = { dashboardItemId: Insight123 }

function makeTrendsQuery(display?: ChartDisplayType): TrendsQuery {
    return {
        kind: NodeKind.TrendsQuery,
        series: [
            {
                kind: NodeKind.EventsNode,
                name: '$pageview',
                event: '$pageview',
                math: BaseMathType.TotalCount,
            },
        ],
        trendsFilter: {
            display,
        },
    }
}

async function openOptionsMenu(): Promise<void> {
    const optionsButtons = screen.getAllByRole('button', { name: /Options/ })
    await userEvent.click(optionsButtons[0])
}

function getDisplaySectionItems(): string[] {
    const displaySection = screen.getByTestId('options-display-section').closest('section')!
    const listItems = within(displaySection).getAllByRole('listitem')
    return listItems.map((li) => li.textContent?.trim() || '')
}

describe('InsightDisplayConfig', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/insights/trend': [],
                '/api/environments/:team_id/insights/': { results: [{}] },
            },
        })
        initKeaTests()
        featureFlagLogic().mount()
    })

    afterEach(() => {
        cleanup()
    })

    function setupAndRender(query: TrendsQuery): void {
        insightLogic(insightProps).mount()
        insightDataLogic(insightProps).mount()
        const vizDataLogic = insightVizDataLogic(insightProps)
        vizDataLogic.mount()
        vizDataLogic.actions.updateQuerySource(query)

        render(
            <Provider>
                <BindLogic logic={insightLogic} props={insightProps}>
                    <InsightDisplayConfig />
                </BindLogic>
            </Provider>
        )
    }

    describe('box plot display options', () => {
        it('only shows "Show legend" in the Display section', async () => {
            setupAndRender(makeTrendsQuery(ChartDisplayType.BoxPlot))
            await openOptionsMenu()

            const items = getDisplaySectionItems()
            expect(items).toEqual(['Show legend'])
        })

        it('shows unit picker and Y-axis scale but not statistical analysis', async () => {
            setupAndRender(makeTrendsQuery(ChartDisplayType.BoxPlot))
            await openOptionsMenu()

            expect(screen.getByText('Y-axis scale')).toBeInTheDocument()
            expect(screen.queryByText('Statistical analysis')).not.toBeInTheDocument()
        })
    })

    describe('line graph display options', () => {
        it('shows multiple options in the Display section', async () => {
            setupAndRender(makeTrendsQuery(ChartDisplayType.ActionsLineGraph))
            await openOptionsMenu()

            const items = getDisplaySectionItems()
            expect(items).toContain('Show legend')
            expect(items).toContain('Show values on series')
            expect(items).toContain('Show alert threshold lines')
            expect(items).toContain('Show trend lines')
        })

        it('shows Y-axis scale section', async () => {
            setupAndRender(makeTrendsQuery(ChartDisplayType.ActionsLineGraph))
            await openOptionsMenu()

            expect(screen.getByText('Y-axis scale')).toBeInTheDocument()
        })
    })
})
