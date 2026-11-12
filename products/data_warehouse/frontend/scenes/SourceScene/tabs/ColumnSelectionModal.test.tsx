import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { ColumnSelectionPicker, ColumnSelectionTarget } from './ColumnSelectionModal'

const COLUMNS = [{ name: 'id' }, { name: 'uuid' }, { name: 'email' }]

const SENSITIVE_COLUMNS: ColumnSelectionTarget['available_columns'] = [
    { name: 'email', data_type: 'text', sensitivity: 'email' },
    { name: 'last_login_ip', data_type: 'text', sensitivity: 'ip_address' },
    { name: 'phone', data_type: 'text', sensitivity: 'phone' },
    { name: 'first_name', data_type: 'text', sensitivity: 'name' },
    { name: 'billing_address', data_type: 'text', sensitivity: 'address' },
    { name: 'plan', data_type: 'text', sensitivity: null },
]

const rowFor = (name: string): HTMLElement =>
    screen.getByText(name, { selector: 'code' }).closest('.justify-between') as HTMLElement

const renderPicker = (schema: Partial<ColumnSelectionTarget>, onMaskedChange = jest.fn()): jest.Mock => {
    render(
        <ColumnSelectionPicker
            hideActions
            enableMasking
            schema={{ id: 'users', available_columns: COLUMNS, ...schema }}
            onMaskedChange={onMaskedChange}
        />
    )
    return onMaskedChange
}

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

    test.each([
        ['the stored key', { primary_key_columns: ['email'], detected_primary_keys: ['uuid'] }, 'email'],
        ['the detected key when none is stored', { detected_primary_keys: ['uuid'] }, 'uuid'],
        ['the id column when no key is known', {}, 'id'],
    ])('only %s cannot be masked', (_name, keys, key) => {
        renderPicker(keys)

        for (const { name } of COLUMNS) {
            const mask = within(rowFor(name)).getByText('Mask').closest('button')
            expect(mask).toHaveAttribute('aria-disabled', String(name === key))
        }
    })

    test.each([
        ['a masked column that became the key', ['uuid'], 'uuid'],
        ['a masked column that left the source', ['gone'], 'gone'],
    ])('%s can still be unmasked', (_name, masked, column) => {
        const onMaskedChange = renderPicker({ detected_primary_keys: ['uuid'], masked_columns: masked })

        fireEvent.click(within(rowFor(column)).getByText('Masked'))

        expect(onMaskedChange).toHaveBeenLastCalledWith([])
    })

    test.each([
        ['on', true, ['Phone', 'Name', 'Address']],
        ['off', false, []],
    ])('with the flag %s, only maskable flagged columns get a chip', (_name, enabled, chips) => {
        const flag = FEATURE_FLAGS.WAREHOUSE_COLUMN_SENSITIVITY
        featureFlagLogic.actions.setFeatureFlags([flag], { [flag]: enabled })
        renderPicker({
            primary_key_columns: ['email'],
            incremental_field: 'last_login_ip',
            available_columns: SENSITIVE_COLUMNS,
        })

        for (const label of ['Email', 'IP address', 'Phone', 'Name', 'Address']) {
            expect(screen.queryByText(label) !== null).toBe(chips.includes(label))
        }
        expect(screen.queryByText('Mask suggested columns') !== null).toBe(enabled)
    })

    test('reports the suggestion count from the saved masks', () => {
        const capture = jest.spyOn(posthog, 'capture')
        renderPicker({
            primary_key_columns: ['email'],
            incremental_field: 'last_login_ip',
            masked_columns: ['phone'],
            available_columns: SENSITIVE_COLUMNS,
        })

        const suggested = capture.mock.calls.filter(([event]) => event === 'warehouse column sensitivity suggested')
        expect(suggested).toEqual([['warehouse column sensitivity suggested', { suggested_count: 2 }]])
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
            const onMaskedChange = renderPicker({
                id: 'customers',
                enabled_columns: null,
                masked_columns: ['phone'],
                incremental_field: 'last_login_ip',
                available_columns: SENSITIVE_COLUMNS,
                ...overrides,
            })

            fireEvent.click(screen.getByText('Mask suggested columns'))

            expect(onMaskedChange).toHaveBeenLastCalledWith(expected)
            expect(screen.queryByText('Mask suggested columns')).not.toBeInTheDocument()
        }
    )
})
