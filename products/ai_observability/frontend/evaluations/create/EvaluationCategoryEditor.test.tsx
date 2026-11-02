import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import type { EvaluationOutputConfig } from '../types'
import { EvaluationCategoryEditor } from './EvaluationCategoryEditor'

describe('EvaluationCategoryEditor', () => {
    afterEach(cleanup)

    it.each([
        { name: 'a new category takes its key from the label', storedKeys: [], key: 'fixed' },
        {
            name: 'a saved category keeps its stored key, which past results use',
            storedKeys: ['resolved'],
            key: 'resolved',
        },
    ])('$name', ({ storedKeys, key }) => {
        const onChange = jest.fn()
        const config: EvaluationOutputConfig = {
            selection_mode: 'single',
            options: [{ key: 'resolved', label: 'Resolved' }],
            passing_rule: { categories: ['resolved'] },
        }
        render(
            <EvaluationCategoryEditor config={config} onChange={onChange} showKeys={false} storedKeys={storedKeys} />
        )

        fireEvent.change(screen.getByLabelText('Category 1'), { target: { value: 'Fixed' } })

        expect(onChange).toHaveBeenCalledWith({
            options: [{ key, label: 'Fixed' }],
            passing_rule: { categories: [key] },
        })
    })
    it('a new row whose label passes through a saved one takes its own key and leaves the pass mark', () => {
        const onChange = jest.fn()
        const config: EvaluationOutputConfig = {
            selection_mode: 'single',
            options: [
                { key: 'helpful', label: 'Helpful' },
                { key: 'helpful', label: 'Helpful' },
            ],
            passing_rule: { categories: ['helpful'] },
        }
        render(
            <EvaluationCategoryEditor config={config} onChange={onChange} showKeys={false} storedKeys={['helpful']} />
        )

        fireEvent.change(screen.getByLabelText('Category 2'), { target: { value: 'Helpful but long' } })

        expect(onChange).toHaveBeenCalledWith({
            options: [config.options![0], { key: 'helpful-but-long', label: 'Helpful but long' }],
            passing_rule: { categories: ['helpful'] },
        })
    })

    it('turning grading off drops the passing rule, so runs only get a category', () => {
        const onChange = jest.fn()
        const config: EvaluationOutputConfig = {
            selection_mode: 'multiple',
            options: [{ key: 'helpful', label: 'Helpful' }],
            passing_rule: { categories: [] },
        }
        render(<EvaluationCategoryEditor config={config} onChange={onChange} showKeys={false} />)

        fireEvent.click(screen.getByLabelText('Grade runs as pass or fail'))

        expect(onChange).toHaveBeenCalledWith({ passing_rule: null })
    })
})
