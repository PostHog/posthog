import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { lemonToast } from 'lib/lemon-ui/LemonToast'

/** Asks before `deleteDashboard` runs, and keeps the dialog open when the delete fails so the person can retry. */
export function openDeleteCrossProjectDashboardDialog(name: string, deleteDashboard: () => Promise<void>): void {
    LemonDialog.open({
        title: 'Delete dashboard?',
        description: `This deletes "${name}" for everyone in your organization. The insights on it stay in their projects.`,
        shouldAwaitSubmit: true,
        primaryButton: {
            children: 'Delete dashboard',
            status: 'danger',
            'data-attr': 'cross-project-dashboard-delete-confirm',
            onClick: async () => {
                try {
                    await deleteDashboard()
                } catch (error: any) {
                    lemonToast.error(error?.detail || 'Could not delete that dashboard. Try again.')
                    throw error
                }
                lemonToast.success('Dashboard deleted')
            },
        },
        secondaryButton: { children: 'Cancel' },
    })
}
