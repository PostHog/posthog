import { useActions, useValues } from 'kea'

import { IconEllipsis, IconInfo } from '@posthog/icons'
import {
    Badge,
    Button,
    Collapsible,
    CollapsibleContent,
    CollapsibleHeader,
    CollapsibleTrigger,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
    Spinner,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { isKeyOf } from 'lib/utils/guards'

import { ProxyRecord, proxyLogic } from './proxyLogic'
import { PROXY_STATUS_TOOLTIPS, statusText } from './proxyStatusText'
import { QuillProxyRecordDetails } from './QuillProxyRecordDetails'

function ProxyStatusBadge({ status }: { status: ProxyRecord['status'] | undefined }): JSX.Element {
    if (!status) {
        return <Badge>Unknown</Badge>
    }

    const tooltip = isKeyOf(status, PROXY_STATUS_TOOLTIPS) ? PROXY_STATUS_TOOLTIPS[status] : null

    return (
        <span className="flex items-center gap-1">
            <Badge variant={status === 'valid' ? 'success' : status === 'erroring' ? 'destructive' : 'warning'}>
                {status === 'issuing' && <Spinner />}
                <span className="capitalize">{isKeyOf(status, statusText) ? statusText[status] : status}</span>
            </Badge>
            {tooltip && (
                <Tooltip>
                    <TooltipTrigger delay={0} render={<Button size="icon-xs" aria-label={tooltip} />}>
                        <IconInfo />
                    </TooltipTrigger>
                    <TooltipContent className="max-w-80">{tooltip}</TooltipContent>
                </Tooltip>
            )}
        </span>
    )
}

export function QuillProxyRecordRow({
    record,
    restrictionReason,
    onDelete,
}: {
    record: ProxyRecord
    restrictionReason: string | null
    onDelete: (id: ProxyRecord['id']) => void
}): JSX.Element {
    const { diagnoseLoadingIds, expandedRecordIds } = useValues(proxyLogic)
    const { diagnose, retryRecord, setRecordExpanded } = useActions(proxyLogic)

    const { id, status, domain } = record
    const isDiagnosing = diagnoseLoadingIds.includes(id)

    return (
        <Collapsible
            open={expandedRecordIds.includes(id)}
            onOpenChange={(open) => setRecordExpanded(id, open)}
            className="rounded-md border border-border p-2"
        >
            <CollapsibleHeader className="flex-wrap">
                <CollapsibleTrigger iconOnly>{`Show details for ${domain}`}</CollapsibleTrigger>
                <Text size="xs" weight="medium" render={<span className="min-w-0 truncate" />}>
                    {domain}
                </Text>
                <ProxyStatusBadge status={status} />
                {status != 'deleting' && !restrictionReason && (
                    <div className="ms-auto">
                        <DropdownMenu>
                            <DropdownMenuTrigger
                                render={
                                    <Button
                                        size="icon"
                                        aria-label={`Actions for ${domain}`}
                                        tooltip={`Actions for ${domain}`}
                                    />
                                }
                            >
                                <IconEllipsis />
                            </DropdownMenuTrigger>
                            <DropdownMenuContent align="end">
                                <DropdownMenuItem
                                    onClick={() => diagnose(id)}
                                    disabledReason={isDiagnosing ? 'A diagnostic is already running' : undefined}
                                >
                                    {isDiagnosing ? 'Running diagnostics…' : 'Diagnose'}
                                </DropdownMenuItem>
                                {(status === 'erroring' || status === 'timed_out') && (
                                    <DropdownMenuItem onClick={() => retryRecord(id)}>Retry</DropdownMenuItem>
                                )}
                                <DropdownMenuItem variant="destructive" onClick={() => onDelete(id)}>
                                    Delete
                                </DropdownMenuItem>
                            </DropdownMenuContent>
                        </DropdownMenu>
                    </div>
                )}
            </CollapsibleHeader>
            <CollapsibleContent className="pt-2">
                <QuillProxyRecordDetails record={record} />
            </CollapsibleContent>
        </Collapsible>
    )
}
