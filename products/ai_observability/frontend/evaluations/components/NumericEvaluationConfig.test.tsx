import { fireEvent, render } from '@testing-library/react'

import { NumericEvaluationConfig } from './NumericEvaluationConfig'

describe('NumericEvaluationConfig', () => {
    it.each(['min', 'max', 'step', 'threshold'])('clears %s without storing NaN', (field) => {
        const onChange = jest.fn()
        const { container } = render(
            <NumericEvaluationConfig
                config={{ min: 1, max: 10, step: 1, passing_rule: { operator: 'gte', threshold: 7 } }}
                onChange={onChange}
            />
        )
        fireEvent.change(container.querySelector(`[data-attr="llma-evaluation-numeric-${field}"]`)!, {
            target: { value: '' },
        })
        expect(onChange).toHaveBeenLastCalledWith(
            field === 'threshold' ? { passing_rule: { operator: 'gte', threshold: 1 } } : { [field]: null }
        )
    })
})
