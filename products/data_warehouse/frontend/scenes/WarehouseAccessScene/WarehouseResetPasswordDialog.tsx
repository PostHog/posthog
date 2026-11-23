import { useActions, useValues } from 'kea'

import {
    AlertDialog,
    AlertDialogClose,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
    Button,
} from '@posthog/quill'

import { warehouseLoginsLogic } from './warehouseLoginsLogic'

export function WarehouseResetPasswordDialog(): JSX.Element {
    const { pendingResetRoot, trinoConnection } = useValues(warehouseLoginsLogic)
    const { requestResetRoot, resetPassword } = useActions(warehouseLoginsLogic)

    return (
        <AlertDialog open={pendingResetRoot} onOpenChange={(open) => requestResetRoot(open)}>
            <AlertDialogContent>
                <AlertDialogHeader>
                    <AlertDialogTitle>{`Reset the password for ${trinoConnection?.username ?? 'root'}?`}</AlertDialogTitle>
                    <AlertDialogDescription>
                        This generates a new password and stops the current one from working. The new password can take
                        up to five minutes to apply. Save it when it is shown.
                    </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                    <AlertDialogClose render={<Button variant="outline" />}>Cancel</AlertDialogClose>
                    <AlertDialogClose
                        render={<Button variant="primary" data-attr="warehouse-access-reset-password-confirm" />}
                        onClick={() => resetPassword()}
                    >
                        Reset password
                    </AlertDialogClose>
                </AlertDialogFooter>
            </AlertDialogContent>
        </AlertDialog>
    )
}
