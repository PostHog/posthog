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
})
