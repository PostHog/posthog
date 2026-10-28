import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import { RowFilterEditor } from './RowFilterEditor'

describe('RowFilterEditor', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    test.each([
        ['every operator is allowed', undefined, '='],
        ['the column limits its operators', ['>', '>=', '<', '<='], '>'],
    ])('a new filter starts on an operator the column accepts when %s', (_name, operators, expected) => {
        const onChange = jest.fn()
        render(
            <RowFilterEditor
                hideActions
                schema={{
                    id: 'orders',
                    row_filters: null,
                    available_columns: [{ name: 'created_at', data_type: 'timestamp', operators }],
                }}
                onChange={onChange}
            />
        )

        fireEvent.click(screen.getByText('Add filter'))

        expect(onChange).toHaveBeenLastCalledWith([{ column: 'created_at', operator: expected, value: '' }])
    })
})
