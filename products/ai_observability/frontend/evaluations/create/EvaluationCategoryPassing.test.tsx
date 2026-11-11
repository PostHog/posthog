import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import type { EvaluationOutputConfig } from '../types'
import { EvaluationCategoryPassing } from './EvaluationCategoryPassing'

describe('EvaluationCategoryPassing', () => {
    afterEach(cleanup)

    it('turning the pass rate off drops the passing rule, so runs only get a category', () => {
        const onChange = jest.fn()
        const config: EvaluationOutputConfig = {
            selection_mode: 'multiple',
            options: [{ key: 'helpful', label: 'Helpful' }],
            passing_rule: { categories: [] },
        }
        render(<EvaluationCategoryPassing config={config} onChange={onChange} />)

        fireEvent.click(screen.getByLabelText('Track a pass rate'))

        expect(onChange).toHaveBeenCalledWith({ passing_rule: null })
    })
})
