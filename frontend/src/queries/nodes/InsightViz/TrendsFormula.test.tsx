import '@testing-library/jest-dom'

import { act, cleanup, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { TrendsFormulaNode } from '~/queries/schema/schema-general'
import { buildTrendsQuery, getQuerySource, INSIGHT_TEST_ID, renderInsightPage } from '~/test/insight-testing'

// Mounting the whole filter editor can outrun Jest's 5s default on a contended shard.
jest.setTimeout(15000)

const FORMULA_PLACEHOLDER = 'Example: (A + B) / 100'

function formulaInputs(): HTMLInputElement[] {
    return screen.queryAllByPlaceholderText(FORMULA_PLACEHOLDER) as HTMLInputElement[]
}

function nodes(...formulas: string[]): TrendsFormulaNode[] {
    return formulas.map((formula) => ({ formula }))
}

/** Rewrite the query's formulas the way the source query editor does. Formula mode stays on,
 *  so TrendsSeries never remounts the editor and its local state has to catch up. */
function rewriteFormulasOutsideTheEditor(formulaNodes: TrendsFormulaNode[]): void {
    act(() => {
        insightVizDataLogic({ dashboardItemId: INSIGHT_TEST_ID }).actions.updateInsightFilter({ formulaNodes })
    })
}

describe('TrendsFormula', () => {
    afterEach(cleanup)

    it('drops the formula from the query when its only input is emptied', async () => {
        renderInsightPage({ query: buildTrendsQuery({ trendsFilter: { formulaNodes: nodes('A') } }) })

        const input = await screen.findByPlaceholderText(FORMULA_PLACEHOLDER)
        await userEvent.clear(input)
        await userEvent.tab()

        await waitFor(() => expect(getQuerySource().trendsFilter?.formulaNodes).toEqual([]))
    })

    const rewrites: [string, TrendsFormulaNode[], TrendsFormulaNode[], string[]][] = [
        ['grown', nodes('A'), nodes('A', 'B', 'C'), ['A', 'B', 'C']],
        ['shrunk', nodes('A', 'B', 'C'), nodes('B'), ['B']],
    ]

    it.each(rewrites)(
        'shows one input per formula after the query has %s elsewhere',
        async (_, initialNodes, rewrittenNodes, expectedInputValues) => {
            renderInsightPage({ query: buildTrendsQuery({ trendsFilter: { formulaNodes: initialNodes } }) })
            await waitFor(() => expect(formulaInputs()).toHaveLength(initialNodes.length))

            rewriteFormulasOutsideTheEditor(rewrittenNodes)

            await waitFor(() => expect(formulaInputs().map((input) => input.value)).toEqual(expectedInputValues))
        }
    )
})
