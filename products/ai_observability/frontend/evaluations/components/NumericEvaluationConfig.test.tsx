import { cleanup, fireEvent, render } from '@testing-library/react'

import { numericOutputConfigError } from '../constants'
import type { EvaluationOutputConfig } from '../types'
import { NumericEvaluationConfig } from './NumericEvaluationConfig'

describe('NumericEvaluationConfig', () => {
    afterEach(cleanup)

    it.each([
        ['min', 'Minimum (optional)'],
        ['max', 'Maximum (optional)'],
        ['step', 'Step (optional)'],
    ])('clears labeled %s without storing NaN', (field, label) => {
        const onChange = jest.fn()
        const config: EvaluationOutputConfig = {
            min: 1,
            max: 10,
            step: 1,
            passing_rule: { operator: 'gte', threshold: 7 },
        }
        const { getByLabelText, rerender } = render(<NumericEvaluationConfig config={config} onChange={onChange} />)
        getByLabelText('Pass when score is')
        const input = getByLabelText(label) as HTMLInputElement
        fireEvent.change(input, {
            target: { value: '' },
        })
        expect(onChange).toHaveBeenLastCalledWith({ [field]: null })
        rerender(<NumericEvaluationConfig config={{ ...config, [field]: null }} onChange={onChange} />)
        fireEvent.blur(input)
        expect(input.value).toBe('')
        fireEvent.change(input, { target: { value: '2' } })
        expect(onChange).toHaveBeenLastCalledWith({ [field]: 2 })
    })

    it('keeps a cleared threshold empty and invalid until a number is entered', () => {
        const onChange = jest.fn()
        const config: EvaluationOutputConfig = { min: 1, max: 10, passing_rule: { operator: 'gte', threshold: 7 } }
        const { getByLabelText, rerender } = render(<NumericEvaluationConfig config={config} onChange={onChange} />)
        const input = getByLabelText('Threshold') as HTMLInputElement
        fireEvent.change(input, { target: { value: '' } })
        const cleared = { ...config, ...onChange.mock.calls[0][0] }
        expect(numericOutputConfigError(cleared)).not.toBeNull()
        rerender(<NumericEvaluationConfig config={cleared} onChange={onChange} />)
        fireEvent.blur(input)
        expect(input.value).toBe('')
        fireEvent.change(input, { target: { value: '5' } })
        const edited = { ...config, ...onChange.mock.calls[1][0] }
        expect(edited.passing_rule.threshold).toBe(5)
        expect(numericOutputConfigError(edited)).toBeNull()
    })
})
