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
})
