import { expectLogic } from 'kea-test-utils'

import { LemonDialog } from '@posthog/lemon-ui'

import { OrganizationMembershipLevel } from 'lib/constants'
import { billingLogic } from 'scenes/billing/billingLogic'
import { organizationLogic } from 'scenes/organizationLogic'

import { initKeaTests } from '~/test/init'
import type { OrganizationType } from '~/types'

import {
    CHECK_NOW_CONFIRMATION_DESCRIPTION,
    billingAlertsLogic,
    mergeUniqueAlerts,
    openBillingAlertCheckNowConfirmation,
} from './billingAlertsLogic'
import * as generatedApi from './generated/api'
import type { BillingAlertConfigurationApi, PaginatedBillingAlertConfigurationListApi } from './generated/api.schemas'

const alert = (id: string): BillingAlertConfigurationApi => ({ id }) as BillingAlertConfigurationApi
const organization = (id: string): OrganizationType =>
    ({ id, membership_level: OrganizationMembershipLevel.Owner }) as OrganizationType
const page = (alerts: BillingAlertConfigurationApi[]): PaginatedBillingAlertConfigurationListApi => ({
    count: alerts.length,
    next: null,
    previous: null,
    results: alerts,
})

describe('billing alerts logic', () => {
    it('deduplicates alerts when a later page overlaps after a live insert', () => {
        expect(
            mergeUniqueAlerts([alert('a'), alert('b')], [alert('b'), alert('c'), alert('c')]).map(({ id }) => id)
        ).toEqual(['a', 'b', 'c'])
    })

    it('confirms live notification side effects before checking', () => {
        const onConfirm = jest.fn()
        const dialog = jest.spyOn(LemonDialog, 'open').mockImplementation(jest.fn())

        openBillingAlertCheckNowConfirmation(onConfirm)

        expect(dialog).toHaveBeenCalledWith(
            expect.objectContaining({
                description: CHECK_NOW_CONFIRMATION_DESCRIPTION,
                primaryButton: expect.objectContaining({ children: 'Check now' }),
            })
        )
        expect(onConfirm).not.toHaveBeenCalled()
        dialog.mock.calls[0][0].primaryButton?.onClick?.({} as never)
        expect(onConfirm).toHaveBeenCalledTimes(1)
    })

    describe('organization changes', () => {
        let unmountOrganization: () => void
        let unmountBilling: () => void
        let unmountAlerts: () => void

        beforeEach(() => {
            initKeaTests()
            unmountOrganization = organizationLogic.mount()
            unmountBilling = billingLogic.mount()
            organizationLogic.actions.loadCurrentOrganizationSuccess(organization('org-a'))
        })

        afterEach(() => {
            unmountAlerts?.()
            unmountBilling?.()
            unmountOrganization?.()
            jest.restoreAllMocks()
        })

        it('clears organization-scoped rows and editor state before loading the next organization', async () => {
            const list = jest.spyOn(generatedApi, 'billingAlertsList').mockResolvedValue(page([alert('a')]))
            unmountAlerts = billingAlertsLogic.mount()
            await expectLogic(billingAlertsLogic).toFinishAllListeners()

            billingAlertsLogic.actions.editAlert(alert('a'))
            billingAlertsLogic.actions.setCheckingAlertId('a')
            billingAlertsLogic.actions.setDeletingAlertId('a', true)
            organizationLogic.actions.loadCurrentOrganizationSuccess(organization('org-b'))

            expect(billingAlertsLogic.values.alertsPage).toEqual(page([]))
            expect(billingAlertsLogic.values.selectedAlert).toBeNull()
            expect(billingAlertsLogic.values.isEditorOpen).toBe(false)
            expect(billingAlertsLogic.values.checkingAlertId).toBeNull()
            expect(billingAlertsLogic.values.deletingAlertIds.size).toBe(0)

            await expectLogic(billingAlertsLogic).toFinishAllListeners()
            expect(list).toHaveBeenLastCalledWith('org-b', { limit: 30 })
        })

        it('does not let a late response from the previous organization overwrite the new page', async () => {
            let resolveOrgA: (value: PaginatedBillingAlertConfigurationListApi) => void = () => undefined
            const orgAResponse = new Promise<PaginatedBillingAlertConfigurationListApi>((resolve) => {
                resolveOrgA = resolve
            })
            jest.spyOn(generatedApi, 'billingAlertsList').mockImplementation((organizationId) =>
                organizationId === 'org-a' ? orgAResponse : Promise.resolve(page([alert('b')]))
            )

            unmountAlerts = billingAlertsLogic.mount()
            organizationLogic.actions.loadCurrentOrganizationSuccess(organization('org-b'))
            await expectLogic(billingAlertsLogic).toFinishAllListeners()
            expect(billingAlertsLogic.values.alerts.map(({ id }) => id)).toEqual(['b'])

            resolveOrgA(page([alert('a')]))
            await Promise.resolve()
            await Promise.resolve()
            expect(billingAlertsLogic.values.alerts.map(({ id }) => id)).toEqual(['b'])
        })
    })
})
