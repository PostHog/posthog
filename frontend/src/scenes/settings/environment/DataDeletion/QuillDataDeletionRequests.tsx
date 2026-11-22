import { Fragment, useState } from 'react'

import { IconChevronDown, IconChevronRight, IconPlus } from '@posthog/icons'
import { LemonTagType } from '@posthog/lemon-ui'
import {
    Badge,
    Button,
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    Skeleton,
    Table,
    TableBody,
    TableCell,
    TableEmpty,
    TableHead,
    TableHeader,
    TableRow,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { TZLabel } from 'lib/components/TZLabel'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'

import type { DataDeletionRequestApi } from '~/generated/core/api.schemas'

type BadgeVariant = 'default' | 'info' | 'destructive' | 'warning' | 'success' | 'completed'

const BADGE_VARIANT: Partial<Record<LemonTagType, BadgeVariant>> = {
    primary: 'info',
    warning: 'warning',
    success: 'success',
    danger: 'destructive',
}

const COLUMN_COUNT = 5

export function QuillDataDeletionRequests({
    requests,
    loading,
    loadFailed,
    onRetry,
    newRequestDisabledReason,
    getStatus,
}: {
    requests: DataDeletionRequestApi[] | null
    loading: boolean
    loadFailed: boolean
    onRetry: () => void
    newRequestDisabledReason: string | null
    getStatus: (request: DataDeletionRequestApi) => { label: string; type: LemonTagType; description: string }
}): JSX.Element {
    const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set())

    const toggleExpanded = (id: string): void =>
        setExpandedIds((current) => {
            const next = new Set(current)
            if (next.has(id)) {
                next.delete(id)
            } else {
                next.add(id)
            }
            return next
        })

    return (
        <div className="flex flex-col items-start gap-4">
            <Button
                variant="primary"
                nativeButton={false}
                render={<LinkPrimitive to={urls.dataDeletionRequestNew()} />}
                disabledReason={newRequestDisabledReason}
                data-attr="data-deletion-new-request"
            >
                <IconPlus />
                New deletion request
            </Button>
            {loadFailed ? (
                <Item tone="destructive" size="sm" className="w-full">
                    <ItemContent>
                        <ItemDescription>
                            Could not load deletion requests. Try again, and contact support if it keeps happening.
                        </ItemDescription>
                    </ItemContent>
                    <ItemActions>
                        <Button variant="outline" onClick={onRetry}>
                            Try again
                        </Button>
                    </ItemActions>
                </Item>
            ) : loading && !requests?.length ? (
                <Skeleton className="h-24 w-full" />
            ) : (
                <Table>
                    <TableHeader>
                        <TableRow>
                            <TableHead className="w-0" />
                            <TableHead>Status</TableHead>
                            <TableHead>Matched events</TableHead>
                            <TableHead>Submitted</TableHead>
                            <TableHead>Approved</TableHead>
                        </TableRow>
                    </TableHeader>
                    {!requests?.length ? (
                        <TableEmpty colSpan={COLUMN_COUNT}>
                            <Text size="xs" variant="muted" render={<p className="m-0" />}>
                                No deletion requests yet. Submitted requests appear here with their status.
                            </Text>
                        </TableEmpty>
                    ) : (
                        <TableBody>
                            {requests.map((request) => {
                                const status = getStatus(request)
                                const expanded = expandedIds.has(request.id)

                                return (
                                    <Fragment key={request.id}>
                                        <TableRow>
                                            <TableCell>
                                                <Button
                                                    size="icon-sm"
                                                    aria-label={expanded ? 'Hide query' : 'Show query'}
                                                    aria-expanded={expanded}
                                                    tooltip={expanded ? 'Hide query' : 'Show query'}
                                                    onClick={() => toggleExpanded(request.id)}
                                                >
                                                    {expanded ? <IconChevronDown /> : <IconChevronRight />}
                                                </Button>
                                            </TableCell>
                                            <TableCell>
                                                <Tooltip>
                                                    <TooltipTrigger
                                                        render={
                                                            <Badge variant={BADGE_VARIANT[status.type] ?? 'default'}>
                                                                {status.label}
                                                            </Badge>
                                                        }
                                                    />
                                                    <TooltipContent>{status.description}</TooltipContent>
                                                </Tooltip>
                                            </TableCell>
                                            <TableCell>
                                                {request.count === null ? (
                                                    <span className="text-muted-foreground">Not counted yet</span>
                                                ) : (
                                                    <span translate="no">{humanFriendlyNumber(request.count)}</span>
                                                )}
                                            </TableCell>
                                            <TableCell>
                                                <TZLabel time={request.created_at} />
                                            </TableCell>
                                            <TableCell>
                                                {request.approved_at ? (
                                                    <TZLabel time={request.approved_at} />
                                                ) : (
                                                    <span className="text-muted-foreground">Not yet</span>
                                                )}
                                            </TableCell>
                                        </TableRow>
                                        {expanded && (
                                            <TableRow>
                                                <TableCell colSpan={COLUMN_COUNT}>
                                                    <CodeSnippet language={Language.SQL} wrap>
                                                        {request.query}
                                                    </CodeSnippet>
                                                </TableCell>
                                            </TableRow>
                                        )}
                                    </Fragment>
                                )
                            })}
                        </TableBody>
                    )}
                </Table>
            )}
        </div>
    )
}
