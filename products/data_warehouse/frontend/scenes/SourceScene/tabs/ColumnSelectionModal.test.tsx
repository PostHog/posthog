import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import { ColumnSelectionPicker } from './ColumnSelectionModal'

describe('ColumnSelectionPicker', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    test('masking suggested columns skips key, incremental and already masked columns', () => {
        const onMaskedChange = jest.fn()
        render(
            <ColumnSelectionPicker
                hideActions
                enableMasking
                schema={{
                    id: 'customers',
                    enabled_columns: null,
                    masked_columns: ['phone'],
                    primary_key_columns: ['email'],
                    incremental_field: 'last_login_ip',
                    available_columns: [
                        { name: 'email', data_type: 'text', sensitivity: 'email' },
                        { name: 'last_login_ip', data_type: 'text', sensitivity: 'ip_address' },
                        { name: 'phone', data_type: 'text', sensitivity: 'phone' },
                        { name: 'first_name', data_type: 'text', sensitivity: 'name' },
                        { name: 'billing_address', data_type: 'text', sensitivity: 'address' },
                        { name: 'plan', data_type: 'text', sensitivity: null },
                    ],
                }}
                onMaskedChange={onMaskedChange}
            />
        )

        expect(screen.getByText('2 columns look like personal or secret data.')).toBeInTheDocument()
        fireEvent.click(screen.getByText('Mask suggested columns'))

        expect(onMaskedChange).toHaveBeenLastCalledWith(['phone', 'first_name', 'billing_address'])
        expect(screen.queryByText('Mask suggested columns')).not.toBeInTheDocument()
    })
})
