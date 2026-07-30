import { renderHook } from '@testing-library/react'

import { useAutofillReconcile } from './useAutofillReconcile'

describe('useAutofillReconcile', () => {
    function inputWithValue(value: string): HTMLInputElement {
        const el = document.createElement('input')
        el.value = value
        return el
    }

    it('syncs an autofilled DOM value that never reached form state', () => {
        const { result } = renderHook(() => useAutofillReconcile())
        result.current.fieldRef('password')(inputWithValue('hunter2!'))

        const setValue = jest.fn()
        result.current.reconcile(setValue)

        expect(setValue).toHaveBeenCalledTimes(1)
        expect(setValue).toHaveBeenCalledWith('password', 'hunter2!')
    })

    it('leaves empty fields untouched so their validation error still surfaces', () => {
        const { result } = renderHook(() => useAutofillReconcile())
        result.current.fieldRef('password')(inputWithValue(''))
        result.current.fieldRef('first_name')(null)

        const setValue = jest.fn()
        result.current.reconcile(setValue)

        expect(setValue).not.toHaveBeenCalled()
    })
})
