import '@testing-library/jest-dom'

import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { filterTestAccountsDefaultsLogic } from 'scenes/settings/environment/filterTestAccountDefaultsLogic'

import { initKeaTests } from '~/test/init'

import { EditSessionReplayWidgetModal } from './EditSessionReplayWidgetModal'

describe('EditSessionReplayWidgetModal', () => {
    afterEach(() => {
        cleanup()
    })

    beforeEach(() => {
        initKeaTests(true, {
            test_account_filters: [{ key: 'email', value: '@posthog.com', operator: 'not_icontains', type: 'person' }],
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
        await userEvent.click(within(dialog).getByRole('button', { name: 'Save' }))

        expect(onSave).toHaveBeenCalledWith(
            expect.objectContaining({
                limit: 10,
                orderBy: 'start_time',
                filterTestAccounts: true,
                dateRange: { date_from: '-7d' },
            })
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

        expect(screen.getByText('Must be an integer between 1 and 25.')).toBeInTheDocument()
        expect(screen.getByRole('button', { name: 'Save' })).toHaveAttribute('aria-disabled', 'true')
        expect(onSave).not.toHaveBeenCalled()
    })
})
