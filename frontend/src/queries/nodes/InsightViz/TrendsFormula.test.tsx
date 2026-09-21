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

    const removals: [string, () => Promise<void>][] = [
        [
            'emptying its only input',
            async () => {
                await userEvent.clear(await screen.findByPlaceholderText(FORMULA_PLACEHOLDER))
                await userEvent.tab()
            },
        ],
        [
            'removing its only input',
            async () => {
                await userEvent.click(await screen.findByTitle('Remove formula and disable formula mode'))
            },
        ],
        [
            'switching formula mode off',
            async () => {
                await screen.findByPlaceholderText(FORMULA_PLACEHOLDER)
                await userEvent.click(screen.getByTestId('trends-formula-switch'))
            },
        ],
    ]

    it.each(removals)('drops the formula from the query and closes the editor when %s', async (_, remove) => {
        renderInsightPage({ query: buildTrendsQuery({ trendsFilter: { formulaNodes: nodes('A') } }) })

        await remove()

        await waitFor(() => {
            expect(getQuerySource().trendsFilter?.formulaNodes).toEqual([])
            expect(screen.queryByText('Add formula')).not.toBeInTheDocument()
        })
    })

    it('closes the editor when the last formula is emptied after another was removed', async () => {
        renderInsightPage({ query: buildTrendsQuery({ trendsFilter: { formulaNodes: nodes('A', 'B') } }) })

        await waitFor(() => expect(formulaInputs()).toHaveLength(2))
        await userEvent.click(screen.getAllByTitle('Remove formula')[1])
        await waitFor(() => expect(getQuerySource().trendsFilter?.formulaNodes).toEqual(nodes('A')))

        await userEvent.clear(formulaInputs()[0])
        await userEvent.tab()

        await waitFor(() => {
            expect(getQuerySource().trendsFilter?.formulaNodes).toEqual([])
            expect(screen.queryByText('Add formula')).not.toBeInTheDocument()
        })
    })

    it('keeps the editor open on a blank input when the only filled formula is removed', async () => {
        renderInsightPage({ query: buildTrendsQuery({ trendsFilter: { formulaNodes: nodes('A') } }) })

        await screen.findByPlaceholderText(FORMULA_PLACEHOLDER)
        await userEvent.click(screen.getByText('Add formula'))
        await userEvent.click(screen.getAllByTitle('Remove formula')[0])

        await waitFor(() => expect(getQuerySource().trendsFilter?.formulaNodes).toEqual([]))
        expect(formulaInputs().map((input) => input.value)).toEqual([''])
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
