import { render } from '@testing-library/react'

import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { InsightShortId } from '~/types'

import { TrendsFormula } from './TrendsFormula'

describe('TrendsFormula', () => {
    // Shared query links carry any `formulas` value, and the deprecated field has held node objects.
    it('shows a formula that the deprecated field holds as a node object', () => {
        useMocks({ get: { '/api/environments/:team_id/insights/': { results: [{}] } } })
        initKeaTests()

        const insightProps = { dashboardItemId: '123' as InsightShortId, cachedInsight: null }
        insightDataLogic(insightProps).mount()
        const logic = insightVizDataLogic(insightProps)
        logic.mount()
        logic.actions.updateQuerySource({
            trendsFilter: { formulas: [{ formula: 'C / A', custom_name: 'Cost per trace' }] },
        } as any)

        const { container } = render(<TrendsFormula insightProps={insightProps} />)

        const inputs = container.querySelectorAll('input')
        expect(inputs[0].value).toBe('C / A')
        expect(inputs[1].value).toBe('Cost per trace')
    })
})
