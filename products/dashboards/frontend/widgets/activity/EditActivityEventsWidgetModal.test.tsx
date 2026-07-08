import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { filterTestAccountsDefaultsLogic } from 'scenes/settings/environment/filterTestAccountDefaultsLogic'

import { initKeaTests } from '~/test/init'
import { PropertyFilterType, PropertyOperator } from '~/types'

import { EditActivityEventsWidgetModal } from './EditActivityEventsWidgetModal'

describe('EditActivityEventsWidgetModal', () => {
    afterEach(() => {
        cleanup()
    })

    beforeEach(() => {
        initKeaTests(true, {
            ...MOCK_DEFAULT_TEAM,
            test_account_filters: [
                {
                    key: 'email',
                    value: '@posthog.com',
                    operator: PropertyOperator.NotIContains,
                    type: PropertyFilterType.Person,
                },
            ],
        })
        filterTestAccountsDefaultsLogic.mount()
    })

    it('saves widget config from default activity settings', async () => {
        const onSave = jest.fn().mockResolvedValue(undefined)

        render(
            <EditActivityEventsWidgetModal
                isOpen
                onClose={jest.fn()}
                config={{
                    limit: 10,
                    filterTestAccounts: true,
                    dateRange: { date_from: '-24h' },
                }}
                onSave={onSave}
            />
        )

        const dialog = screen.getByRole('dialog')
        await userEvent.click(within(dialog).getByText('Save'))

        expect(onSave).toHaveBeenCalledWith(
            expect.objectContaining({
                limit: 10,
                filterTestAccounts: true,
                dateRange: { date_from: '-24h' },
            }),
            {}
        )
    })

    it('shows inline error for limit above 50 instead of saving', async () => {
        const onSave = jest.fn()

        render(
            <EditActivityEventsWidgetModal
                isOpen
                onClose={jest.fn()}
                config={{ limit: 10, dateRange: { date_from: '-24h' } }}
                onSave={onSave}
            />
        )

        const limitInput = screen.getByRole('spinbutton')
        await userEvent.clear(limitInput)
        await userEvent.type(limitInput, '60')

        expect(screen.getByText('Too big: expected number to be <=50')).toBeInTheDocument()
        expect(screen.getByText('Save').closest('button')).toHaveAttribute('aria-disabled', 'true')
        expect(onSave).not.toHaveBeenCalled()
    })
})
