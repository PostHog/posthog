import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import { RenameViewModal } from './RenameViewModal'

describe('RenameViewModal', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(cleanup)

    it('links a blocked model to its model page by saved query id', () => {
        render(
            <RenameViewModal
                viewName="orders_by_day"
                name="orders_by_week"
                isSaving={false}
                references={[]}
                referencesLoading={false}
                referencesError={false}
                inline
                plan={{
                    name: 'orders_by_week',
                    dependents: [],
                    blocked: [{ id: 'saved-query-1', name: 'revenue_report', reason: 'Its query does not parse.' }],
                    joins: [],
                    plan_token: 'token',
                }}
                onNameChange={() => undefined}
                onClose={() => undefined}
                onSubmit={() => undefined}
            />
        )

        expect(screen.getByText('revenue_report').closest('a')).toHaveAttribute(
            'href',
            expect.stringMatching(/\/models\/saved-query-1\?lookup=saved_query$/)
        )
    })

    const blocked = { id: 'saved-query-1', name: 'revenue_report', reason: 'Its query does not parse.' }
    const dependent = { id: 'saved-query-2', name: 'orders_report', before: 'a', after: 'b' }
    const join = {
        id: 'join-1',
        field_name: 'customer',
        source_table_name_before: 'orders_by_day',
        source_table_name_after: 'orders_by_week',
        joining_table_name_before: 'customers',
        joining_table_name_after: 'customers',
    }

    it.each([
        ['no plan yet and no known references', undefined, /^No known views reference this one\./],
        ['a plan with nothing to update', { dependents: [], blocked: [] }, /^No other views reference this one\./],
        ['a plan with a blocked view', { dependents: [], blocked: [blocked] }, /^Views that reference this one/],
        ['a plan with a view to update', { dependents: [dependent], blocked: [] }, /^Views that reference this one/],
    ])('warns about other references for %s', (_case, plan, expected) => {
        render(
            <RenameViewModal
                viewName="orders_by_day"
                name="orders_by_week"
                isSaving={false}
                references={[]}
                referencesLoading={false}
                referencesError={false}
                inline
                plan={plan && { name: 'orders_by_week', plan_token: 'token', joins: [], ...plan }}
                onNameChange={() => undefined}
                onClose={() => undefined}
                onSubmit={() => undefined}
            />
        )

        expect(screen.getByText(expected)).toBeInTheDocument()
    })

    it.each([
        ['views only', [dependent, { ...dependent, id: 'saved-query-3' }], [], 'Rename and update 2 views'],
        ['a join only', [], [join], 'Rename and update 1 join'],
        [
            'views and joins',
            [dependent, { ...dependent, id: 'saved-query-3' }],
            [join, { ...join, id: 'join-2', field_name: 'refunds' }],
            'Rename and update 2 views and 2 joins',
        ],
    ])('lists the joins the rename updates and counts them for %s', (_case, dependents, joins, button) => {
        render(
            <RenameViewModal
                viewName="orders_by_day"
                name="orders_by_week"
                isSaving={false}
                references={[]}
                referencesLoading={false}
                referencesError={false}
                inline
                plan={{ name: 'orders_by_week', dependents, blocked: [], joins, plan_token: 'token' }}
                onNameChange={() => undefined}
                onClose={() => undefined}
                onSubmit={() => undefined}
            />
        )

        expect(screen.getByRole('button', { name: button })).toBeInTheDocument()
        for (const item of joins) {
            expect(screen.getByText(`orders_by_week.${item.field_name} → customers`)).toBeInTheDocument()
        }
    })
})
