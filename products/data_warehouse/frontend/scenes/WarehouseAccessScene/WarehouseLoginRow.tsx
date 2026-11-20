import { useActions, useValues } from 'kea'

import { IconEllipsis } from '@posthog/icons'
import {
    Badge,
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
    TableCell,
    TableRow,
} from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import type { WarehouseLoginApi } from 'products/data_warehouse/frontend/generated/api.schemas'

import { formatBytes } from '../WarehouseConsole/warehouseConsoleFormat'
import { warehouseLoginActions } from './warehouseLoginActions'
import { warehouseLoginsLogic } from './warehouseLoginsLogic'

// pinned: the data-attr values in this file feed autocapture and dashboards, so renaming them breaks both.

export function WarehouseLoginRow({ login }: { login: WarehouseLoginApi }): JSX.Element {
    const { busyUsername } = useValues(warehouseLoginsLogic)
    const { rotateLogin, setLoginDisabled, requestDeleteLogin } = useActions(warehouseLoginsLogic)
    const actions = warehouseLoginActions(login.kind)
    const busy = busyUsername !== null

    return (
        <TableRow>
            <TableCell className="font-mono">{login.username}</TableCell>
            <TableCell>{login.scope_label}</TableCell>
            <TableCell>
                <Badge variant={login.disabled ? 'warning' : 'success'}>{login.disabled ? 'Disabled' : 'Active'}</Badge>
            </TableCell>
            <TableCell>{humanFriendlyNumber(login.queries_30d)}</TableCell>
            <TableCell>{formatBytes(login.billable_bytes_30d)}</TableCell>
            <TableCell>{login.created_at ? <TZLabel time={login.created_at} /> : '-'}</TableCell>
            <TableCell>
                {actions.canRotate || actions.canDisable || actions.canDelete ? (
                    <DropdownMenu>
                        <DropdownMenuTrigger
                            render={
                                <Button
                                    size="icon-sm"
                                    loading={busyUsername === login.username}
                                    disabled={busy}
                                    aria-label={`Actions for ${login.username}`}
                                    data-attr="warehouse-access-login-actions"
                                />
                            }
                        >
                            <IconEllipsis />
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
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
