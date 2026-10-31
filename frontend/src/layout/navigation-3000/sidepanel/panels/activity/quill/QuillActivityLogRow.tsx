import clsx from 'clsx'
import { router } from 'kea-router'
import { useId, useState } from 'react'

import { IconCollapse, IconExpand } from '@posthog/icons'
import {
    Button,
    Tabs,
    TabsContent,
    TabsList,
    TabsTrigger,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { ActivityClientTag } from 'lib/components/ActivityLog/ActivityClientTag'
import { ActivityLogDiff } from 'lib/components/ActivityLog/ActivityLogDiff'
import { ACTIVITY_SEARCH_PARAM } from 'lib/components/ActivityLog/activityLogLogic'
import { AgentAttribution } from 'lib/components/ActivityLog/AgentAttribution'
import { HumanizedActivityLogItem } from 'lib/components/ActivityLog/humanizeActivity'
import { QuillPersonAvatar } from 'lib/components/QuillPersonAvatar/QuillPersonAvatar'
import { TZLabel } from 'lib/components/TZLabel'
import { IconLink } from 'lib/lemon-ui/icons'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

type ActivityLogTab = 'details' | 'extended description' | 'diff' | 'raw'

function IconButton({
    label,
    onClick,
    children,
    ...props
}: {
    label: string
    onClick: () => void
    children: React.ReactNode
    'aria-expanded'?: boolean
    'aria-controls'?: string
    'data-attr'?: string
    className?: string
}): JSX.Element {
    return (
        <Tooltip>
            <TooltipTrigger
                delay={0}
                render={<Button size="icon-xs" aria-label={label} onClick={onClick} {...props} />}
            >
                {children}
            </TooltipTrigger>
            <TooltipContent>{label}</TooltipContent>
        </Tooltip>
    )
}

// Serializes only when the Raw tab renders, since payloads can be large and most rows stay collapsed.
function RawPayload({ value }: { value: unknown }): JSX.Element {
    return <pre>{JSON.stringify(value, null, 2)}</pre>
}

export function QuillActivityLogRow({ logItem }: { logItem: HumanizedActivityLogItem }): JSX.Element {
    const [expanded, setExpanded] = useState(false)
    const [activeTab, setActiveTab] = useState<ActivityLogTab>(logItem.expandedView ? 'details' : 'diff')
    const detailsId = useId()

    const copyLink = (): void => {
        if (!logItem.id) {
            return
        }
        const { pathname, search, hash } = router.values.currentLocation
        const url = new URL(pathname, window.location.origin)
        url.search = search || ''
        url.hash = hash || ''
        url.searchParams.delete(ACTIVITY_SEARCH_PARAM)
        url.searchParams.set(ACTIVITY_SEARCH_PARAM, logItem.id)
        void copyToClipboard(url.toString(), 'activity link')
    }

    const avatar = (
        <QuillPersonAvatar
            name={logItem.name ?? ''}
            email={logItem.email ?? undefined}
            system={logItem.isSystem || logItem.wasImpersonated}
        />
    )

    const heading = (
        <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs">
            {logItem.summary?.actor}
            {logItem.client && <ActivityClientTag client={logItem.client} />}
            <span className="text-muted-foreground">
                <TZLabel time={logItem.created_at} />
            </span>
        </div>
    )

    const tabs = [
        logItem.expandedView && {
            key: 'details' as const,
            label: logItem.expandedView.label,
            content: logItem.expandedView.content,
        },
        logItem.extendedDescription && {
            key: 'extended description' as const,
            label: 'Extended description',
            content: <div>{logItem.extendedDescription}</div>,
        },
        { key: 'diff' as const, label: 'Diff', content: <ActivityLogDiff logItem={logItem} /> },
        {
            key: 'raw' as const,
            label: 'Raw',
            content: <RawPayload value={logItem.unprocessed} />,
        },
    ].filter(Boolean) as { key: ActivityLogTab; label: string; content: React.ReactNode }[]

    return (
        <div
            className={clsx(
                'group/activity flex flex-col rounded-md text-xs',
                expanded && 'border border-border',
                logItem.unread && 'bg-fill-selected'
            )}
        >
            <div className="flex gap-2 p-2">
                {logItem.emailToReveal ? (
                    <Tooltip>
                        <TooltipTrigger delay={200} render={<span className="flex shrink-0 self-start" />}>
                            {avatar}
                        </TooltipTrigger>
                        <TooltipContent className="ph-no-capture">{logItem.emailToReveal}</TooltipContent>
                    </Tooltip>
                ) : (
                    <span className="flex shrink-0 self-start">{avatar}</span>
                )}
                {/* Long resource names have no spaces to break on, so they wrap anywhere to fit the panel. */}
                <div className="flex min-w-0 flex-1 flex-col gap-1 [overflow-wrap:anywhere]">
                    {logItem.summary ? (
                        <>
                            {heading}
                            <div
                                className={clsx(
                                    'font-semibold first-letter:uppercase',
                                    !expanded && 'line-clamp-2 focus-within:line-clamp-none'
                                )}
                            >
                                {logItem.summary.action}
                            </div>
                            <div className="text-muted-foreground">{logItem.summary.target}</div>
                            {logItem.summary.preview && (
                                <div className={clsx('text-muted-foreground', !expanded && 'line-clamp-2')}>
                                    {logItem.summary.preview}
                                </div>
                            )}
                        </>
                    ) : (
                        <div>{logItem.description}</div>
                    )}
                    {logItem.extendedDescription && <div>{logItem.extendedDescription}</div>}
                    <div className="empty:hidden">
                        <AgentAttribution logItem={logItem} truncateIntent={!expanded} />
                    </div>
                    {!logItem.summary && heading}
                </div>
                <div className="flex shrink-0 items-start gap-0.5">
                    {logItem.id && (
                        <IconButton
                            label="Copy link to this activity"
                            onClick={copyLink}
                            className="opacity-0 group-focus-within/activity:opacity-100 group-hover/activity:opacity-100"
                        >
                            <IconLink />
                        </IconButton>
                    )}
                    <IconButton
                        label={expanded ? 'Collapse activity details' : 'Expand activity details'}
                        onClick={() => setExpanded(!expanded)}
                        aria-expanded={expanded}
                        aria-controls={expanded ? detailsId : undefined}
                        data-attr="activity-log-expand"
                    >
                        {expanded ? <IconCollapse /> : <IconExpand />}
                    </IconButton>
                </div>
            </div>
            {expanded && (
                <Tabs
                    id={detailsId}
                    value={activeTab}
                    onValueChange={(value) => setActiveTab(value as ActivityLogTab)}
                    className="min-w-0 gap-2 px-2 pb-2 [&_pre]:whitespace-pre-wrap [&_pre]:break-words"
                >
                    <TabsList>
                        {tabs.map((tab) => (
                            <TabsTrigger key={tab.key} value={tab.key}>
                                {tab.label}
                            </TabsTrigger>
                        ))}
                    </TabsList>
                    {tabs.map((tab) => (
                        <TabsContent
                            key={tab.key}
                            value={tab.key}
                            // The shared diff titles each field with an h2, which reads as a page heading at this size.
                            className="min-w-0 overflow-x-auto [&_h2]:m-0 [&_h2]:text-xs [&_h2]:font-semibold"
                        >
                            {tab.content}
                        </TabsContent>
                    ))}
                </Tabs>
            )}
        </div>
    )
}
