import './ActivityLog.scss'

import clsx from 'clsx'
import { router } from 'kea-router'
import { useEffect, useId, useRef, useState } from 'react'

import { IconCollapse, IconExpand } from '@posthog/icons'
import { LemonButton, LemonTabs, Tooltip } from '@posthog/lemon-ui'

import { ActivityClientTag } from 'lib/components/ActivityLog/ActivityClientTag'
import { TZLabel } from 'lib/components/TZLabel'
import { IconLink } from 'lib/lemon-ui/icons'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { ActivityLogDiff } from './ActivityLogDiff'
import { ACTIVITY_SEARCH_PARAM } from './activityLogLogic'
import { AgentAttribution } from './AgentAttribution'
import { HumanizedActivityLogItem } from './humanizeActivity'

type ActivityLogTabs = 'details' | 'extended description' | 'diff' | 'raw'

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

    const handleCopyLink = (): void => {
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
                {/* Tooltip merges the trigger props onto its child element, and ProfilePicture drops props
                    it does not declare, so the trigger must land on the span instead of the avatar. */}
                <Tooltip
                    title={
                        logItem.emailToReveal ? (
                            <span className="ph-no-capture">{logItem.emailToReveal}</span>
                        ) : undefined
                    }
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
                <div className="ActivityLogRow__details min-w-0 flex-1">
                    <div className="mb-1.5 flex flex-wrap items-center gap-x-2 gap-y-0.5">
                        {logItem.summary?.actor}
                        {logItem.client && <ActivityClientTag client={logItem.client} />}
                        <span className="text-secondary text-xs @min-[35rem]:ml-auto">
                            <TZLabel time={logItem.created_at} />
                        </span>
                    </div>
                    {logItem.summary ? (
                        <>
                            <div className="ActivityLogRow__summary font-semibold first-letter:uppercase">
                                {logItem.summary.action}
                            </div>
                            <div className="text-secondary">{logItem.summary.target}</div>
                            {logItem.summary.preview && (
                                <div className={clsx('mt-2 text-secondary font-normal', !isExpanded && 'line-clamp-2')}>
                                    {logItem.summary.preview}
                                </div>
                            )}
                        </>
                    ) : (
                        <div className="ActivityLogRow__description">{logItem.description}</div>
                    )}
                    {logItem.extendedDescription && (
                        <div className="ActivityLogRow__description__extended">{logItem.extendedDescription}</div>
                    )}
                    <div className="mt-2 empty:hidden">
                        <AgentAttribution logItem={logItem} truncateIntent={!isExpanded} />
                    </div>
                </div>
                {logItem.id && (
                    <LemonButton
                        noPadding={true}
                        icon={<IconLink />}
                        onClick={handleCopyLink}
                        tooltip="Copy link to this activity"
                        className="ActivityLogRow__copy-link"
                        aria-label="Copy link to this activity"
                    />
                )}
                <LemonButton
                    noPadding={true}
                    icon={isExpanded ? <IconCollapse /> : <IconExpand />}
                    onClick={() => setIsExpanded(!isExpanded)}
                    active={isExpanded}
                    aria-label={isExpanded ? 'Collapse activity details' : 'Expand activity details'}
                    aria-expanded={isExpanded}
                    aria-controls={isExpanded ? detailsId : undefined}
                    data-attr="activity-log-expand"
                />
            </div>
            {isExpanded && (
                <div id={detailsId} className="min-w-0 px-1 py-0.5 [&_pre]:whitespace-pre-wrap [&_pre]:break-words">
                    <LemonTabs
                        activeKey={activeTab}
                        onChange={(key) => setActiveTab(key as ActivityLogTabs)}
                        tabs={[
                            logItem.expandedView
                                ? {
                                      key: 'details',
                                      label: logItem.expandedView.label,
                                      content: logItem.expandedView.content,
                                  }
                                : false,
                            logItem.extendedDescription
                                ? {
                                      key: 'extended description',
                                      label: 'Extended Description',
                                      tooltip:
                                          'Some activities have a more detailed description that is not shown when collapsed.',
                                      content: (
                                          <div>
                                              {logItem.extendedDescription
                                                  ? logItem.extendedDescription
                                                  : 'This item has no extended description'}
                                          </div>
                                      ),
                                  }
                                : false,
                            {
                                key: 'diff',
                                label: 'Diff',
                                tooltip:
                                    'Show the diff of the changes made to the item. Each activity item could have more than one change.',
                                content: <ActivityLogDiff logItem={logItem} />,
                            },
                            {
                                key: 'raw',
                                label: 'Raw',
                                tooltip: 'Show the raw data of the activity item.',
                                content: (
                                    <div>
                                        <pre>{JSON.stringify(logItem.unprocessed, null, 2)}</pre>
                                    </div>
                                ),
                            },
                        ]}
                    />
                </div>
            )}
        </div>
    )
}
