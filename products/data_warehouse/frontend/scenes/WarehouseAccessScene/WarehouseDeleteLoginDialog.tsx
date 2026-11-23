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

export function WarehouseDeleteLoginDialog(): JSX.Element {
    const { pendingDeleteUsername } = useValues(warehouseLoginsLogic)
    const { requestDeleteLogin, deleteLogin } = useActions(warehouseLoginsLogic)

    return (
        <AlertDialog
            open={pendingDeleteUsername !== null}
            onOpenChange={(open) => {
                if (!open) {
                    requestDeleteLogin(null)
                }
            }}
        >
            <AlertDialogContent>
                <AlertDialogHeader>
                    <AlertDialogTitle>{`Delete ${pendingDeleteUsername ?? 'this login'}?`}</AlertDialogTitle>
                    <AlertDialogDescription>
                        Anything still using its password stops connecting. This cannot be undone.
                    </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                    <AlertDialogClose render={<Button variant="outline" />}>Cancel</AlertDialogClose>
                    <AlertDialogClose
                        render={
                            <Button variant="destructive-outline" data-attr="warehouse-access-login-delete-confirm" />
                        }
                        onClick={() => pendingDeleteUsername && deleteLogin(pendingDeleteUsername)}
                    >
                        Delete login
                    </AlertDialogClose>
                </AlertDialogFooter>
            </AlertDialogContent>
        </AlertDialog>
    )
}
