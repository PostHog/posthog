import { useActions, useValues } from 'kea'

import { IconArchive, IconFolder, IconPin, IconPinFilled, IconX } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuTrigger,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { TodaySessionBulkArchiveDialog } from './TodaySessionBulkArchiveDialog'
import { sessionsLabel } from './todaySessionSelection'
import { TodayBulkAction, todaySessionSelectionLogic } from './todaySessionSelectionLogic'
import { TodaySpaceFileList } from './TodaySpaceFileList'
import { todaySpacesLogic } from './todaySpacesLogic'

const BUSY_REASON = 'Wait for the current change to finish'

interface BulkButtonProps {
    label: string
    action: TodayBulkAction | null
    icon: JSX.Element
    dataAttr: string
    onClick?: () => void
    /** Wraps the button before the tooltip does, so it can open a menu. */
    wrap?: (button: JSX.Element) => JSX.Element
}

/** The sidebar is narrow, so each action is an icon button that names itself in its tooltip, like Desktop's bar. */
function BulkButton({ label, action, icon, dataAttr, onClick, wrap }: BulkButtonProps): JSX.Element {
    const { bulkAction } = useValues(todaySessionSelectionLogic)
    const loading = action !== null && bulkAction === action
    const busy = bulkAction !== null && !loading
    const button = (
        <Button
            size="icon-sm"
            aria-label={label}
            loading={loading}
            disabled={busy}
            onClick={onClick}
            data-attr={dataAttr}
        />
    )
    return (
        <Tooltip>
            <TooltipTrigger delay={0} render={wrap ? wrap(button) : button}>
                {icon}
            </TooltipTrigger>
            <TooltipContent side="top">{busy ? BUSY_REASON : label}</TooltipContent>
        </Tooltip>
    )
}

export function TodaySessionBulkBar(): JSX.Element {
    const { selectedSessionIds, bulkPinDirection } = useValues(todaySessionSelectionLogic)
    const { pinSelected, fileSelectedTo, requestBulkArchive, clearSelection } = useActions(todaySessionSelectionLogic)
    const { spaces } = useValues(todaySpacesLogic)
    const count = selectedSessionIds.length
    const sessions = sessionsLabel(count)
    const pin = bulkPinDirection === 'pin'

    return (
        <>
            {/* The bar is the only sign of a selection and unmounts below two, so the announcement lives outside it. */}
            <span aria-live="polite" className="sr-only">
                {count > 1 ? `${sessions} selected` : ''}
            </span>
            {count > 1 && (
                <div
                    className="-mx-3 flex items-center justify-between gap-2 border-t border-border px-3 py-1.5"
                    data-attr="today-session-bulk-bar"
                >
                    <div className="flex min-w-0 items-baseline gap-1.5">
                        <Text size="xs" weight="medium" render={<span />} className="shrink-0">
                            {`${count} selected`}
                        </Text>
                        <Text size="xxs" variant="muted" render={<span />} className="truncate">
                            Esc to clear
                        </Text>
                    </div>
                    <div className="flex shrink-0 items-center gap-0.5">
                        <BulkButton
                            label={`${pin ? 'Pin' : 'Unpin'} ${sessions}`}
                            action="pin"
                            icon={pin ? <IconPin /> : <IconPinFilled />}
                            onClick={pinSelected}
                            dataAttr="today-session-bulk-pin"
                        />
                        {spaces.length > 0 && (
                            <DropdownMenu>
                                <BulkButton
                                    label={`File ${sessions} to a space`}
                                    action="file"
                                    icon={<IconFolder />}
                                    wrap={(button) => <DropdownMenuTrigger render={button} />}
                                    dataAttr="today-session-bulk-file"
                                />
                                <DropdownMenuContent align="end" side="top" className="max-h-80 w-64">
                                    <TodaySpaceFileList
                                        currentSpaceId={null}
                                        onSelect={fileSelectedTo}
                                        itemDataAttr="today-session-bulk-file-space"
                                        searchDataAttr="today-session-bulk-file-search"
                                    />
                                </DropdownMenuContent>
                            </DropdownMenu>
                        )}
                        <BulkButton
                            label={`Archive ${sessions}`}
                            action="archive"
                            icon={<IconArchive />}
                            onClick={requestBulkArchive}
                            dataAttr="today-session-bulk-archive"
                        />
                        <BulkButton
                            label="Clear selection"
                            action={null}
                            icon={<IconX />}
                            onClick={clearSelection}
                            dataAttr="today-session-bulk-clear"
                        />
                    </div>
                </div>
            )}
            <TodaySessionBulkArchiveDialog />
        </>
    )
}
