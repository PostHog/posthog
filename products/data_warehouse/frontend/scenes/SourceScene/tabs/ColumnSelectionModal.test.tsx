import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import { ColumnSelectionPicker, ColumnSelectionTarget } from './ColumnSelectionModal'

const COLUMNS = [{ name: 'id' }, { name: 'uuid' }, { name: 'email' }]

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
})
