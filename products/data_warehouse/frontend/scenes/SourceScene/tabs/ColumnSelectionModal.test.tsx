import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { ColumnSelectionPicker, ColumnSelectionTarget } from './ColumnSelectionModal'

const COLUMNS: ColumnSelectionTarget['available_columns'] = [
    { name: 'email', data_type: 'text', sensitivity: 'email' },
    { name: 'last_login_ip', data_type: 'text', sensitivity: 'ip_address' },
    { name: 'phone', data_type: 'text', sensitivity: 'phone' },
    { name: 'first_name', data_type: 'text', sensitivity: 'name' },
    { name: 'billing_address', data_type: 'text', sensitivity: 'address' },
    { name: 'plan', data_type: 'text', sensitivity: null },
]

describe('ColumnSelectionPicker', () => {
    beforeEach(() => {
        initKeaTests()
        const flag = FEATURE_FLAGS.WAREHOUSE_COLUMN_SENSITIVITY
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([flag], { [flag]: true })
    })

    afterEach(() => {
        cleanup()
    })

    test.each<[string, Partial<ColumnSelectionTarget>, string[]]>([
        ['a stored key', { primary_key_columns: ['email'] }, ['phone', 'first_name', 'billing_address']],
        ['a detected key', { detected_primary_keys: ['email'] }, ['phone', 'first_name', 'billing_address']],
        [
            'a deselected column',
            {
                primary_key_columns: ['email'],
                enabled_columns: ['email', 'last_login_ip', 'phone', 'first_name', 'plan'],
            },
            ['phone', 'first_name'],
        ],
    ])(
        'masking suggested columns skips %s, the incremental field and already masked columns',
        (_name, overrides, expected) => {
            const onMaskedChange = jest.fn()
            render(
                <ColumnSelectionPicker
                    hideActions
                    enableMasking
                    schema={{
                        id: 'customers',
                        enabled_columns: null,
                        masked_columns: ['phone'],
                        incremental_field: 'last_login_ip',
                        available_columns: COLUMNS,
                        ...overrides,
                    }}
                    onMaskedChange={onMaskedChange}
                />
            )

            fireEvent.click(screen.getByText('Mask suggested columns'))

            expect(onMaskedChange).toHaveBeenLastCalledWith(expected)
            expect(screen.queryByText('Mask suggested columns')).not.toBeInTheDocument()
        }
    )
})
