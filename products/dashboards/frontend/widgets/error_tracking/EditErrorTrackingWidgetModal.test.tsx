import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { filterTestAccountsDefaultsLogic } from 'scenes/settings/environment/filterTestAccountDefaultsLogic'

import { initKeaTests } from '~/test/init'
import { PropertyFilterType, PropertyOperator } from '~/types'

import { exceptionIngestionLogic } from 'products/error_tracking/frontend/components/SetupPrompt/exceptionIngestionLogic'

import { EditErrorTrackingWidgetModal } from './EditErrorTrackingWidgetModal'
import * as errorTrackingWidgetUtils from './utils'

describe('EditErrorTrackingWidgetModal', () => {
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
        featureFlagLogic.mount()
        filterTestAccountsDefaultsLogic.mount()
        exceptionIngestionLogic.mount()
        exceptionIngestionLogic.actions.loadExceptionIngestionStateSuccess(true)
        jest.spyOn(errorTrackingWidgetUtils, 'canConfigureErrorTrackingWidgetIssues').mockReturnValue(true)
    })

    afterEach(() => {
        jest.restoreAllMocks()
        cleanup()
    })

    it('shows inline error for limit above 25 instead of saving', async () => {
        const onSave = jest.fn()

        render(
            <EditErrorTrackingWidgetModal
                isOpen
                onClose={jest.fn()}
                config={{ limit: 10, orderBy: 'occurrences', dateRange: { date_from: '-7d' } }}
                onSave={onSave}
            />
        )

        const limitInput = screen.getByRole('spinbutton')
        await userEvent.clear(limitInput)
        await userEvent.type(limitInput, '30')

        expect(screen.getByText('Too big: expected number to be <=25')).toBeInTheDocument()
        expect(screen.getByRole('button', { name: 'Save' })).toHaveAttribute('aria-disabled', 'true')
        expect(onSave).not.toHaveBeenCalled()
    })

    it('saves title and description from widget settings modal', async () => {
        const onSave = jest.fn().mockResolvedValue(undefined)

        render(
            <EditErrorTrackingWidgetModal
                isOpen
                onClose={jest.fn()}
                config={{ limit: 10, orderBy: 'occurrences', dateRange: { date_from: '-7d' } }}
                name=""
                defaultTitle="Top issues"
                description=""
                onSave={onSave}
            />
        )

        await userEvent.type(screen.getByPlaceholderText('Top issues'), 'Critical crashes')
        await userEvent.type(screen.getByPlaceholderText('Enter description (optional)'), 'Top crashes this week')
        const dialog = screen.getByRole('dialog')
        await userEvent.click(within(dialog).getByRole('button', { name: 'Save' }))

        expect(onSave).toHaveBeenCalledTimes(1)
        expect(onSave).toHaveBeenCalledWith(
            expect.objectContaining({
                limit: 10,
                orderBy: 'occurrences',
            }),
            {
                name: 'Critical crashes',
                description: 'Top crashes this week',
            }
        )
    })

    it('saves filterTestAccounts from widget settings modal', async () => {
        const onSave = jest.fn().mockResolvedValue(undefined)

        render(
            <EditErrorTrackingWidgetModal
                isOpen
                onClose={jest.fn()}
                config={{
                    limit: 10,
                    orderBy: 'occurrences',
                    dateRange: { date_from: '-7d' },
                    filterTestAccounts: true,
                }}
                onSave={onSave}
            />
        )

        await userEvent.click(screen.getByRole('switch', { name: /Filter out internal and test users/i }))
        const dialog = screen.getByRole('dialog')
        await userEvent.click(within(dialog).getByRole('button', { name: 'Save' }))

        expect(onSave).toHaveBeenCalledWith(
            expect.objectContaining({
                filterTestAccounts: false,
            }),
            {}
        )
    })

    it('disables save while request is in flight', async () => {
        let resolveSave: (() => void) | undefined
        const onSave = jest.fn(
            () =>
                new Promise<void>((resolve) => {
                    resolveSave = resolve
                })
        )

        render(
            <EditErrorTrackingWidgetModal
                isOpen
                onClose={jest.fn()}
                config={{ limit: 10, orderBy: 'occurrences', dateRange: { date_from: '-7d' } }}
                onSave={onSave}
            />
        )

        const dialog = screen.getByRole('dialog')
        await userEvent.click(within(dialog).getByRole('button', { name: 'Save' }))

        expect(within(dialog).getByRole('button', { name: 'Save' })).toHaveAttribute('aria-disabled', 'true')
        expect(within(dialog).getByRole('button', { name: 'Cancel' })).toHaveAttribute('aria-disabled', 'true')

        resolveSave?.()
        await within(dialog).findByRole('button', { name: 'Save' })
    })

    it('hides issue settings when exception ingestion is not configured', () => {
        jest.spyOn(errorTrackingWidgetUtils, 'canConfigureErrorTrackingWidgetIssues').mockReturnValue(false)

        render(
            <EditErrorTrackingWidgetModal
                isOpen
                onClose={jest.fn()}
                config={{ limit: 10, orderBy: 'occurrences', dateRange: { date_from: '-7d' } }}
                name=""
                defaultTitle="Top issues"
                description=""
                onSave={jest.fn()}
            />
        )

        expect(screen.getByPlaceholderText('Top issues')).toBeInTheDocument()
        expect(screen.queryByRole('spinbutton')).not.toBeInTheDocument()
        expect(screen.queryByText('Sort by')).not.toBeInTheDocument()
        expect(screen.queryByText(/Filter out internal and test users/i)).not.toBeInTheDocument()
    })
})
