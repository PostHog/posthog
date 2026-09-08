import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { dayjs } from 'lib/dayjs'

import { initKeaTests } from '~/test/init'

import type { CustomPropertyDefinitionApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { AccountCustomPropertyEditor } from './AccountCustomPropertyEditor'
import { AccountPropertyValue } from './AccountPropertyValue'

describe('AccountCustomPropertyEditor', () => {
    const definition: CustomPropertyDefinitionApi = {
        id: 'property-1',
        name: 'Property',
        display_type: 'percent',
        is_canonical: false,
        has_workflow_reference: false,
        source: null,
        created_at: '2026-01-01T00:00:00Z',
        created_by: 1,
        updated_at: null,
        references: [],
    }

    beforeEach(() => initKeaTests())
    afterEach(cleanup)

    it.each([
        [0.184, '18.4', '25', 0.25],
        [0, '0', '0', 0],
        [null, '', '10', 0.1],
    ])('edits stored percent %s in percentage units', (value, shown, entered, expected) => {
        const onSave = jest.fn()
        const { container } = render(
            <AccountCustomPropertyEditor definition={definition} value={value} onSave={onSave} onCancel={jest.fn()} />
        )
        const input = container.querySelector('input')!
        expect(input.value).toBe(shown)
        fireEvent.change(input, { target: { value: entered } })
        fireEvent.click(screen.getByText('Save'))
        expect(onSave).toHaveBeenCalledWith(expected)
    })

    it.each(['date', 'datetime'] as const)(
        'retains an attempted %s selection when the save does not succeed',
        (display_type) => {
            const onSave = jest.fn()
            const value = '2026-01-01T00:00:00+00:00'
            const { container } = render(
                <AccountCustomPropertyEditor
                    definition={{ ...definition, display_type }}
                    value={value}
                    onSave={onSave}
                    onCancel={jest.fn()}
                />
            )
            fireEvent.click(container.querySelector('[data-attr="account-property-date-input"]')!)
            const calendar = document.querySelector('[data-attr="lemon-calendar-select"]')!
            const day = [...calendar.querySelectorAll('[data-attr="lemon-calendar-day"]')].find(
                (el) => el.textContent === '15'
            )!
            fireEvent.click(day)
            fireEvent.click(calendar.querySelector('[data-attr="lemon-calendar-select-apply"]')!)
            expect(onSave).toHaveBeenCalledTimes(1)
            const attempted = onSave.mock.calls[0][0]
            expect(dayjs(attempted).date()).toBe(15)
            expect(container.querySelector('[data-attr="account-property-date-input"]')).toHaveTextContent(
                dayjs(attempted).format(display_type === 'datetime' ? 'MMM D, YYYY HH:mm' : 'MMM D, YYYY')
            )
        }
    )

    it('keeps a UTC-midnight date on the same calendar day in the display and editor', () => {
        const dateDefinition = { ...definition, display_type: 'date' as const }
        const value = '2026-01-01T00:00:00+00:00'
        const { container } = render(
            <>
                <AccountPropertyValue
                    property={{
                        key: 'custom:property-1',
                        kind: 'custom',
                        definition: dateDefinition,
                        value,
                        provenance: 'manual',
                    }}
                />
                <AccountCustomPropertyEditor
                    definition={dateDefinition}
                    value={value}
                    onSave={jest.fn()}
                    onCancel={jest.fn()}
                />
            </>
        )
        expect(screen.getAllByText('Jan 1, 2026')).toHaveLength(2)
        fireEvent.click(container.querySelector('[data-attr="account-property-date-input"]')!)
        const selected = document.querySelector('[data-attr="lemon-calendar-day"].LemonButton--primary')
        expect(selected).toHaveTextContent('1')
    })
})
