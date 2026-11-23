import clsx from 'clsx'

import { IconClock } from '@posthog/icons'
import {
    Badge,
    Button,
    CardDescription,
    CardTitle,
    Spinner,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { IconLink } from 'lib/lemon-ui/icons'
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
    queryScanTooltip,
    queryScanActionable,
    warehouseSyncTooltip,
    onCopyLink,
}: InsightMetaContentProps): JSX.Element {
    const hasTitleIndicator = !!(infoPopover || queryScanTooltip || warehouseSyncTooltip || onCopyLink)
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
            <CardTitle
                role="heading"
                aria-level={4}
                data-attr="insight-card-title"
                className={clsx('flex min-h-7 min-w-0 items-center', hasTitleIndicator && 'overflow-visible')}
            >
                {link ? (
                    <LinkPrimitive to={link} className="max-w-full truncate text-foreground">
                        {titleContent}
                    </LinkPrimitive>
                ) : (
                    titleContent
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
                {onCopyLink && (
                    <Button
                        size="icon-xs"
                        className="CardMeta__copy-link ml-0.5 shrink-0"
                        onClick={onCopyLink}
                        tooltip="Copy link to insight"
                        aria-label="Copy link to insight"
                        data-attr="insight-card-title-copy-link"
                    >
                        <IconLink className="size-3.5" />
                    </Button>
                )}
            </CardTitle>
            {showDescription !== false && !!description && (
                <CardDescription className="leading-4">
                    <LemonMarkdown className="CardMeta__description" lowKeyHeadings>
                        {description}
                    </LemonMarkdown>
                </CardDescription>
            )}
        </>
    )
}
