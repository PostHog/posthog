import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { filterTestAccountsDefaultsLogic } from 'scenes/settings/environment/filterTestAccountDefaultsLogic'

import { initKeaTests } from '~/test/init'
import { PropertyFilterType, PropertyOperator } from '~/types'

import { EditSessionReplayWidgetModal } from './EditSessionReplayWidgetModal'

describe('EditSessionReplayWidgetModal', () => {
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

    it('saves widget config from default session replay settings', async () => {
        const onSave = jest.fn().mockResolvedValue(undefined)

        render(
            <EditSessionReplayWidgetModal
                isOpen
                onClose={jest.fn()}
                config={{
                    limit: 10,
                    orderBy: 'start_time',
                    orderDirection: 'DESC',
                    filterTestAccounts: true,
                    dateRange: { date_from: '-7d' },
                }}
                onSave={onSave}
            />
        )

        const dialog = screen.getByRole('dialog')
        await userEvent.click(within(dialog).getByText('Save'))

        expect(onSave).toHaveBeenCalledWith(
            expect.objectContaining({
                limit: 10,
                orderBy: 'start_time',
                orderDirection: 'DESC',
                filterTestAccounts: true,
                dateRange: { date_from: '-7d' },
            }),
            {}
        )
    })

    it('shows inline error for limit above 25 instead of saving', async () => {
        const onSave = jest.fn()

        render(
            <EditSessionReplayWidgetModal
                isOpen
                onClose={jest.fn()}
                config={{ limit: 10, orderBy: 'start_time', dateRange: { date_from: '-7d' } }}
                onSave={onSave}
            />
        )

        const limitInput = screen.getByRole('spinbutton')
        await userEvent.clear(limitInput)
        await userEvent.type(limitInput, '30')

        expect(screen.getByText('Too big: expected number to be <=25')).toBeInTheDocument()
        expect(screen.getByText('Save').closest('button')).toHaveAttribute('aria-disabled', 'true')
        expect(onSave).not.toHaveBeenCalled()
    })
})
