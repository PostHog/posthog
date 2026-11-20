import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import {
    AlertDialog,
    AlertDialogClose,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
    AlertDialogTrigger,
    Button,
    Card,
    CardContent,
    CardHeader,
    CardTitle,
    Text,
} from '@posthog/quill'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'

import { WarehouseCopyButton } from '../WarehouseConnectScene/WarehouseCopyButton'
import { warehouseConsoleLogic } from '../WarehouseConsole/warehouseConsoleLogic'

// pinned: the data-attr values and analytics event names in this file feed autocapture and dashboards, so renaming them breaks both.

export function WarehouseLoginCard(): JSX.Element {
    const { trinoConnection, isResettingPassword } = useValues(warehouseConsoleLogic)
    const { resetPassword } = useActions(warehouseConsoleLogic)
    const adminRestrictionReason = useRestrictedArea({
        scope: RestrictionScope.Organization,
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
    })

    return (
        <Card>
            <CardHeader>
                <CardTitle>Warehouse login</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
                {trinoConnection ? (
                    <div className="flex min-w-0 items-center justify-between gap-2 rounded-md border px-3 py-2">
                        <div className="min-w-0">
                            <Text size="xs" variant="muted" render={<div />}>
                                Username
                            </Text>
                            <Text size="sm" className="block truncate font-mono" render={<code />}>
                                {trinoConnection.username}
                            </Text>
                        </div>
                        <WarehouseCopyButton
                            iconOnly
                            value={trinoConnection.username}
                            thing="username"
                            target="login_username"
                        />
                    </div>
                ) : (
                    <Text size="sm" variant="muted">
                        The username is temporarily unavailable. Refresh to try again.
                    </Text>
                )}
                <Text size="sm">The password is shown once, when the warehouse is set up. You can reset it here.</Text>
                {adminRestrictionReason ? (
                    <Text size="sm" variant="muted">
                        Ask an organization admin to reset the password.
                    </Text>
                ) : (
                    <div>
                        <AlertDialog>
                            <AlertDialogTrigger
                                render={
                                    <Button
                                        loading={isResettingPassword}
                                        onClick={() => posthog.capture('warehouse access reset password clicked')}
                                        data-attr="warehouse-access-reset-password"
                                    />
                                }
                            >
                                Reset password
                            </AlertDialogTrigger>
                            <AlertDialogContent>
                                <AlertDialogHeader>
                                    <AlertDialogTitle>Reset the warehouse password?</AlertDialogTitle>
                                    <AlertDialogDescription>
                                        This generates a new password and stops the current one from working. The new
                                        password can take up to five minutes to apply. Save it when it is shown.
                                    </AlertDialogDescription>
                                </AlertDialogHeader>
                                <AlertDialogFooter>
                                    <AlertDialogClose render={<Button variant="outline" />}>Cancel</AlertDialogClose>
                                    <AlertDialogClose
                                        render={<Button variant="primary" />}
                                        onClick={() => resetPassword()}
                                    >
                                        Reset password
                                    </AlertDialogClose>
                                </AlertDialogFooter>
                            </AlertDialogContent>
                        </AlertDialog>
                    </div>
                )}
            </CardContent>
        </Card>
    )
}
