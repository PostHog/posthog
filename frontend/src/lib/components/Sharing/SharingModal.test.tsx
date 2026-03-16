import { fireEvent, render, screen } from '@testing-library/react'

import { InsightShortId, QueryBasedInsightModel } from '~/types'

import { SharingModal, SharingModalProps } from './SharingModal'

function renderDashboardSharingModal(extraProps: Partial<SharingModalProps> = {}): void {
    const props: SharingModalProps = {
        isOpen: true,
        closeModal: () => {},
        dashboardId: 123,
        title: 'Dashboard permissions & sharing',
        ...extraProps,
    }

    render(<SharingModal {...props} />)
}

describe('SharingModal (dashboard)', () => {
    it('renders Auto refresh switch when sharing is enabled', async () => {
        renderDashboardSharingModal()

        // Sharing section label
        expect(await screen.findByText('Sharing')).toBeInTheDocument()

        // Options sub header
        expect(screen.getByText('Options')).toBeInTheDocument()

        // Auto refresh switch
        const autoRefreshSwitch = screen.getByText('Auto refresh')
        expect(autoRefreshSwitch).toBeInTheDocument()
    })

    it('toggles Auto refresh value in form state', async () => {
        renderDashboardSharingModal()

        const autoRefreshSwitch = await screen.findByText('Auto refresh')

        // Kea forms wiring means clicking the switch should update the underlying value
        // This is a smoke test that the control is interactive – we don't introspect Kea state here,
        // just ensure the checkbox element toggles.
        const checkbox = autoRefreshSwitch.closest('label')?.querySelector('input[type="checkbox"]') as HTMLInputElement
        expect(checkbox).toBeTruthy()

        const initialChecked = checkbox.checked
        fireEvent.click(autoRefreshSwitch)
        expect(checkbox.checked).toBe(!initialChecked)
    })
})

describe('SharingModal (insight)', () => {
    const fakeInsight: Partial<QueryBasedInsightModel> = {
        id: 456,
        short_id: 'insight456' as InsightShortId,
        name: 'My insight',
    }

    function renderInsightSharingModal(extraProps: Partial<SharingModalProps> = {}): void {
        const props: SharingModalProps = {
            isOpen: true,
            closeModal: () => {},
            title: 'Insight permissions & sharing',
            insightShortId: fakeInsight.short_id,
            insight: fakeInsight,
            previewIframe: true,
            ...extraProps,
        }

        render(<SharingModal {...props} />)
    }

    it('shows insight-specific options and no dashboard-only options', async () => {
        renderInsightSharingModal()

        // Insight option: Show title and description (insight-specific toggle)
        expect(await screen.findByText(/Show title and description/i)).toBeInTheDocument()

        // Dashboard-only options should not be present
        expect(screen.queryByText(/Auto refresh/i)).toBeNull()
        expect(screen.queryByText(/Show insight details/i)).toBeNull()
    })
})
