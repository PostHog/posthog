import { cleanup, fireEvent, render } from '@testing-library/react'

import { NumericEvaluationConfig } from './NumericEvaluationConfig'

describe('NumericEvaluationConfig', () => {
    afterEach(cleanup)

    it.each([
        ['min', 'Minimum (optional)'],
        ['max', 'Maximum (optional)'],
        ['step', 'Step (optional)'],
        ['threshold', 'Threshold'],
    ])('clears labeled %s without storing NaN', (field, label) => {
        const onChange = jest.fn()
        const { getByRole } = render(
            <NumericEvaluationConfig
                config={{ min: 1, max: 10, step: 1, passing_rule: { operator: 'gte', threshold: 7 } }}
                onChange={onChange}
            />
        )
        getByRole('button', { name: 'Pass when score is' })
        fireEvent.change(getByRole('spinbutton', { name: label }), {
            target: { value: '' },
        })
        expect(onChange).toHaveBeenLastCalledWith(
            field === 'threshold' ? { passing_rule: { operator: 'gte', threshold: 1 } } : { [field]: null }
        )
    })
})
