import './ActivityLog.scss'

import clsx from 'clsx'
import { router } from 'kea-router'
import { useEffect, useId, useRef, useState } from 'react'

import { IconCollapse, IconExpand } from '@posthog/icons'
import { LemonButton, LemonTabs, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { IconLink } from 'lib/lemon-ui/icons'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { ActivityLogDiff } from './ActivityLogDiff'
import { ACTIVITY_SEARCH_PARAM } from './activityLogLogic'
import { AgentAttribution } from './AgentAttribution'
import { HumanizedActivityLogItem } from './humanizeActivity'

type ActivityLogTabs = 'details' | 'extended description' | 'diff' | 'raw'

// the expanded panel only re-renders on tab change, so keep the tab list apart from the row body
function ExpandedDetails({
    logItem,
    detailsId,
    activeTab,
    onTabChange,
}: {
    logItem: HumanizedActivityLogItem
    detailsId: string
    activeTab: ActivityLogTabs
    onTabChange: (tab: ActivityLogTabs) => void
}): JSX.Element {
    const tabs = [
        logItem.expandedView && {
            key: 'details' as const,
            label: logItem.expandedView.label,
            content: logItem.expandedView.content,
        },
        logItem.extendedDescription && {
            key: 'extended description' as const,
            label: 'Extended Description',
            tooltip: 'Some activities have a more detailed description that is not shown when collapsed.',
            content: <div>{logItem.extendedDescription}</div>,
        },
        {
            key: 'diff' as const,
            label: 'Diff',
            tooltip:
                'Show the diff of the changes made to the item. Each activity item could have more than one change.',
            content: <ActivityLogDiff logItem={logItem} />,
        },
        {
            key: 'raw' as const,
            label: 'Raw',
            tooltip: 'Show the raw data of the activity item.',
            content: (
                <div>
                    <pre>{JSON.stringify(logItem.unprocessed, null, 2)}</pre>
                </div>
            ),
        },
    ].filter(Boolean) as { key: ActivityLogTabs; label: string; content: JSX.Element; tooltip?: string }[]

    return (
        <div id={detailsId} className="min-w-0 px-1 py-0.5 [&_pre]:whitespace-pre-wrap [&_pre]:break-words">
            <LemonTabs activeKey={activeTab} onChange={onTabChange} tabs={tabs} />
        </div>
    )
}

function RowSummary({ logItem, isExpanded }: { logItem: HumanizedActivityLogItem; isExpanded: boolean }): JSX.Element {
    if (!logItem.summary) {
        return <div className="ActivityLogRow__description">{logItem.description}</div>
    }

    return (
        <>
            <div
                className={clsx(
                    'ActivityLogRow__summary font-semibold first-letter:uppercase',
                    !isExpanded && 'line-clamp-2 focus-within:line-clamp-none'
                )}
            >
                {logItem.summary.action}
            </div>
            <div className="text-secondary">{logItem.summary.target}</div>
            {logItem.summary.preview && (
                <div className={clsx('mt-2 text-secondary font-normal', !isExpanded && 'line-clamp-2')}>
                    {logItem.summary.preview}
                </div>
            )}
        </>
    )
}

function RowBody({ logItem, isExpanded }: { logItem: HumanizedActivityLogItem; isExpanded: boolean }): JSX.Element {
    return (
        <div className="ActivityLogRow__details min-w-0 flex-1">
            {logItem.summary && <RowHeading logItem={logItem} />}
            <RowSummary logItem={logItem} isExpanded={isExpanded} />
            {logItem.extendedDescription && (
                <div className="ActivityLogRow__description__extended">{logItem.extendedDescription}</div>
            )}
            <div className="mt-2 empty:hidden">
                <AgentAttribution logItem={logItem} truncateIntent={!isExpanded} />
            </div>
            {!logItem.summary && <RowHeading logItem={logItem} />}
        </div>
    )
}

function ExpandButton({
    isExpanded,
    onToggle,
    detailsId,
}: {
    isExpanded: boolean
    onToggle: () => void
    detailsId: string
}): JSX.Element {
    return (
        <LemonButton
            noPadding={true}
            icon={isExpanded ? <IconCollapse /> : <IconExpand />}
            onClick={onToggle}
            active={isExpanded}
            aria-label={isExpanded ? 'Collapse activity details' : 'Expand activity details'}
            aria-expanded={isExpanded}
            aria-controls={isExpanded ? detailsId : undefined}
            data-attr="activity-log-expand"
        />
    )
}

function useCopyActivityLink(id?: string): () => void {
    return (): void => {
        if (!id) {
            return
        }
        const { pathname, search, hash } = router.values.currentLocation
        const url = new URL(pathname, window.location.origin)
        url.search = search || ''
        url.hash = hash || ''
        url.searchParams.delete(ACTIVITY_SEARCH_PARAM)
        url.searchParams.set(ACTIVITY_SEARCH_PARAM, id)
        void copyToClipboard(url.toString(), 'activity link')
    }
}

function CopyLinkButton({ onCopy }: { onCopy: () => void }): JSX.Element {
    return (
        <LemonButton
            noPadding={true}
            icon={<IconLink />}
            onClick={onCopy}
            tooltip="Copy link to this activity"
            className="ActivityLogRow__copy-link"
            aria-label="Copy link to this activity"
        />
    )
}

function RowHeading({ logItem }: { logItem: HumanizedActivityLogItem }): JSX.Element {
    return (
        <div className={clsx('flex flex-wrap items-center gap-x-2 gap-y-0.5', logItem.summary ? 'mb-1.5' : 'mt-1.5')}>
            {logItem.summary?.actor}
            {logItem.client && (
                <Tooltip title="Self-reported by the API client in the x-posthog-client request header">
                    <LemonTag size="small" type="muted">
                        via {logItem.client === 'mcp' ? 'MCP' : logItem.client}
                    </LemonTag>
                </Tooltip>
            )}
            <span className={clsx('text-secondary text-xs', logItem.summary && '@min-[35rem]:ml-auto')}>
                <TZLabel time={logItem.created_at} />
            </span>
        </div>
    )
}

function RowActor({ logItem }: { logItem: HumanizedActivityLogItem }): JSX.Element {
    // Tooltip merges the trigger props onto its child element, and ProfilePicture drops props
    // it does not declare, so the trigger must land on the span instead of the avatar.
    return (
        <Tooltip
            title={logItem.emailToReveal ? <span className="ph-no-capture">{logItem.emailToReveal}</span> : undefined}
        >
            <span className="flex shrink-0 self-start">
                <ProfilePicture
                    showName={false}
                    user={{
                        first_name: logItem.isSystem || logItem.wasImpersonated ? logItem.name : undefined,
                        email: logItem.email ?? undefined,
                    }}
                    type={logItem.isSystem || logItem.wasImpersonated ? 'system' : 'person'}
                    size="lg"
                />
            </span>
        </Tooltip>
    )
}

export const ActivityLogRow = ({
    logItem,
    highlighted,
}: {
    logItem: HumanizedActivityLogItem
    highlighted?: boolean
}): JSX.Element => {
    const [isExpanded, setIsExpanded] = useState(false)
    const [activeTab, setActiveTab] = useState<ActivityLogTabs>(logItem.expandedView ? 'details' : 'diff')
    const rowRef = useRef<HTMLDivElement>(null)
    const detailsId = useId()

    useEffect(() => {
        if (highlighted && rowRef.current) {
            rowRef.current.scrollIntoView({ behavior: 'smooth', block: 'center' })
            setIsExpanded(true)
        }
    }, [highlighted])

    const handleCopyLink = useCopyActivityLink(logItem.id)

    return (
        <div
            ref={rowRef}
            className={clsx(
                'ActivityLogRow-wrapper flex flex-col px-1 py-0.5 @container',
                isExpanded && 'border rounded',
                highlighted && 'ActivityLogRow--highlighted'
            )}
        >
            <div className={clsx('ActivityLogRow flex gap-2 py-3', logItem.unread && 'ActivityLogRow--unread')}>
                <RowActor logItem={logItem} />
                <RowBody logItem={logItem} isExpanded={isExpanded} />
                {logItem.id && <CopyLinkButton onCopy={handleCopyLink} />}
                <ExpandButton
                    isExpanded={isExpanded}
                    onToggle={() => setIsExpanded(!isExpanded)}
                    detailsId={detailsId}
                />
            </div>
            {isExpanded && (
                <ExpandedDetails
                    logItem={logItem}
                    detailsId={detailsId}
                    activeTab={activeTab}
                    onTabChange={(key) => setActiveTab(key)}
                />
            )}
        </div>
    )
}
