import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { IconEllipsis } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
    TableCell,
    TableRow,
} from '@posthog/quill'

import type { WarehouseLoginApi } from 'products/data_warehouse/frontend/generated/api.schemas'

import { formatBytes, formatCount } from '../WarehouseConsole/warehouseConsoleFormat'
import { WarehouseStatusBadge } from '../WarehouseConsole/WarehouseStatusBadge'
import { WarehouseTime } from '../WarehouseConsole/WarehouseTime'
import { warehouseLoginActions } from './warehouseLoginActions'
import { warehouseLoginsLogic } from './warehouseLoginsLogic'

// pinned: the data-attr values and analytics event names in this file feed autocapture and dashboards, so renaming them breaks both.

export function WarehouseLoginRow({ login }: { login: WarehouseLoginApi }): JSX.Element {
    const { busyUsername, isResettingPassword } = useValues(warehouseLoginsLogic)
    const { rotateLogin, setLoginDisabled, requestDeleteLogin, requestResetRoot } = useActions(warehouseLoginsLogic)
    const actions = warehouseLoginActions(login.kind)
    const busy = busyUsername !== null || isResettingPassword
    const loading = busyUsername === login.username || (login.kind === 'root' && isResettingPassword)

    return (
        <TableRow>
            <TableCell className="max-w-48 truncate font-mono" title={login.username}>
                {login.username}
            </TableCell>
            <TableCell className="max-w-56 truncate" title={login.scope_label}>
                {login.kind === 'root' ? 'Root, full access' : login.scope_label}
            </TableCell>
            <TableCell>
                <WarehouseStatusBadge status={login.disabled ? 'disabled' : 'active'} />
            </TableCell>
            <TableCell className="text-right tabular-nums">{formatCount(login.queries_30d)}</TableCell>
            <TableCell className="text-right tabular-nums">{formatBytes(login.billable_bytes_30d)}</TableCell>
            <TableCell className="whitespace-nowrap">
                {login.created_at ? <WarehouseTime iso={login.created_at} /> : '-'}
            </TableCell>
            <TableCell className="w-10 text-right">
                {actions.canRotate || actions.canDisable || actions.canDelete || actions.canReset ? (
                    <DropdownMenu>
                        <DropdownMenuTrigger
                            render={
                                <Button
                                    size="icon-sm"
                                    loading={loading}
                                    disabled={busy}
                                    aria-label={`Actions for ${login.username}`}
                                    data-attr="warehouse-access-login-actions"
                                />
                            }
                        >
                            <IconEllipsis />
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                            {actions.canReset && (
                                <DropdownMenuItem
                                    onClick={() => {
                                        posthog.capture('warehouse access reset password clicked')
                                        requestResetRoot(true)
                                    }}
                                    data-attr="warehouse-access-reset-password"
                                >
                                    Reset password
                                </DropdownMenuItem>
                            )}
                            {actions.canRotate && (
                                <DropdownMenuItem
                                    onClick={() => rotateLogin(login.username)}
                                    data-attr="warehouse-access-login-rotate"
                                >
                                    Rotate password
                                </DropdownMenuItem>
                            )}
                            {actions.canDisable && (
                                <DropdownMenuItem
                                    onClick={() => setLoginDisabled(login.username, !login.disabled)}
                                    data-attr="warehouse-access-login-toggle"
                                >
                                    {login.disabled ? 'Enable' : 'Disable'}
                                </DropdownMenuItem>
                            )}
                            {actions.canDelete && (
                                <DropdownMenuItem
                                    onClick={() => requestDeleteLogin(login.username)}
                                    data-attr="warehouse-access-login-delete"
                                >
                                    Delete
                                </DropdownMenuItem>
                            )}
                        </DropdownMenuContent>
                    </DropdownMenu>
                ) : null}
            </TableCell>
        </TableRow>
    )
}
