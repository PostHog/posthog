import { useActions, useValues } from 'kea'

import {
    AlertDialog,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
    Button,
} from '@posthog/quill'

import { dashboardV2Logic } from './dashboardV2Logic'

export function DashboardV2DeleteDialog(): JSX.Element {
    const { deleteDialogOpen, deletedLoading } = useValues(dashboardV2Logic)
    const { setDeleteDialogOpen, deleteDashboard } = useActions(dashboardV2Logic)

    return (
        <AlertDialog open={deleteDialogOpen} onOpenChange={(open: boolean) => setDeleteDialogOpen(open)}>
            <AlertDialogContent>
                <AlertDialogHeader>
                    <AlertDialogTitle>Delete this dashboard?</AlertDialogTitle>
                    <AlertDialogDescription>
                        The dashboard and its panels go away for everyone in the project.
                    </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                    <Button variant="outline" onClick={() => setDeleteDialogOpen(false)}>
                        Cancel
                    </Button>
                    <Button
                        variant="destructive-outline"
                        loading={deletedLoading}
                        onClick={() => deleteDashboard()}
                        data-attr="dashboard-v2-delete-confirm"
                    >
                        Delete
                    </Button>
                </AlertDialogFooter>
            </AlertDialogContent>
        </AlertDialog>
    )
}
