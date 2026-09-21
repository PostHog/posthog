import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'

import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { useMocks } from '~/mocks/jest'
import { TrendsQuery } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { InsightLogicProps, InsightShortId } from '~/types'

import { TrendsFormula } from './TrendsFormula'

describe('TrendsFormula', () => {
    const insightProps: InsightLogicProps = { dashboardItemId: '123' as InsightShortId }
    let logic: ReturnType<typeof insightVizDataLogic.build>

    const formulaNodes = (): unknown =>
        (logic.values.querySource as TrendsQuery | null)?.trendsFilter?.formulaNodes ?? []

    beforeEach(() => {
        useMocks({ get: { '/api/environments/:team_id/insights/': { results: [{}] } } })
        initKeaTests()
        insightDataLogic(insightProps).mount()
        logic = insightVizDataLogic(insightProps)
        logic.mount()
    })

    afterEach(() => {
        cleanup()
    })

    const seedFormula = (formula: string): void => {
        act(() => logic.actions.updateQuerySource({ trendsFilter: { formulaNodes: [{ formula }] } }))
    }

    it('applies an edited formula to the query without waiting for a debounce', () => {
        seedFormula('A/B')
        render(<TrendsFormula insightProps={insightProps} />)

        const input = screen.getByPlaceholderText('Example: (A + B) / 100')
        act(() => {
            fireEvent.change(input, { target: { value: 'A+B' } })
            fireEvent.blur(input)
        })

        expect(formulaNodes()).toEqual([{ formula: 'A+B' }])
    })

    it('clears the query formula when the only filled row is removed, and stays open', () => {
        seedFormula('A/B')
        render(<TrendsFormula insightProps={insightProps} />)

        act(() => void fireEvent.click(screen.getByRole('button', { name: 'Add formula' })))
        act(() => void fireEvent.click(screen.getAllByTitle('Remove formula')[0]))

        expect(formulaNodes()).toEqual([])
        expect(screen.getByPlaceholderText('Example: (A + B) / 100')).toHaveValue('')
    })
})
