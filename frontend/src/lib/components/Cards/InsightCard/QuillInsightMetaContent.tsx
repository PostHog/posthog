import clsx from 'clsx'

import { IconClock, IconWarning } from '@posthog/icons'
import { Badge, Heading, Spinner, Text, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

import type { InsightMetaContentProps } from './InsightMeta'

function TitleIndicator({ tooltip, children }: { tooltip: React.ReactNode; children: JSX.Element }): JSX.Element {
    return (
        <Tooltip>
            <TooltipTrigger render={<span className="ml-1.5 inline-flex shrink-0" tabIndex={0} />}>
                {children}
            </TooltipTrigger>
            <TooltipContent>{tooltip}</TooltipContent>
        </Tooltip>
    )
}

export function QuillInsightMetaContent({
    title,
    fallbackTitle,
    description,
    link,
    loading,
    loadingQueued,
    showDescription,
    infoPopover,
    dataRetentionWarning,
    queryScanTooltip,
    queryScanActionable,
    warehouseSyncTooltip,
}: InsightMetaContentProps): JSX.Element {
    const hasTitleIndicator = !!(infoPopover || dataRetentionWarning || queryScanTooltip || warehouseSyncTooltip)
    const titleContent = (
        <>
            <span className={clsx(hasTitleIndicator && 'truncate')}>
                {title || <i>{fallbackTitle || 'Untitled'}</i>}
            </span>
            {(loading || loadingQueued) && (
                <span
                    className={clsx(
                        'ml-1.5 inline-flex items-center gap-1.5 text-sm font-medium',
                        loading ? 'text-accent' : 'text-muted'
                    )}
                >
                    <Spinner />
                    <span>{loading ? 'Loading' : 'Waiting to load'}</span>
                </span>
            )}
        </>
    )

    return (
        <>
            <Heading
                size="sm"
                render={
                    <h4
                        data-attr="insight-card-title"
                        className={clsx(hasTitleIndicator && 'inline-flex items-center overflow-visible')}
                    />
                }
            >
                {link ? (
                    <LinkPrimitive to={link} className="max-w-full truncate text-foreground">
                        {titleContent}
                    </LinkPrimitive>
                ) : (
                    titleContent
                )}
                {dataRetentionWarning && (
                    <TitleIndicator tooltip={dataRetentionWarning}>
                        <IconWarning className="text-base text-warning" />
                    </TitleIndicator>
                )}
                {queryScanTooltip && (
                    <TitleIndicator tooltip={queryScanTooltip}>
                        {queryScanActionable ? (
                            <Badge variant="warning" data-attr="insight-card-query-scan">
                                Slow query
                            </Badge>
                        ) : (
                            <IconClock className="text-base text-secondary" data-attr="insight-card-query-scan-note" />
                        )}
                    </TitleIndicator>
                )}
                {warehouseSyncTooltip && (
                    <TitleIndicator tooltip={warehouseSyncTooltip}>
                        <Badge variant="warning" data-attr="insight-card-warehouse-sync">
                            Out of date
                        </Badge>
                    </TitleIndicator>
                )}
                {infoPopover}
            </Heading>
            {showDescription !== false && !!description && (
                <Text size="xs" variant="muted" render={<div />}>
                    <LemonMarkdown className="CardMeta__description" lowKeyHeadings>
                        {description}
                    </LemonMarkdown>
                </Text>
            )}
        </>
    )
}
