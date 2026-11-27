import './ActivityLog.scss'

import clsx from 'clsx'
import { useEffect, useId, useRef, useState } from 'react'

import { IconCollapse, IconExpand } from '@posthog/icons'
import { Button, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { IconLink } from 'lib/lemon-ui/icons'

import { HumanizedActivityLogItem } from './humanizeActivity'
import { QuillActivityLogActor } from './QuillActivityLogActor'
import { QuillActivityLogDetails, QuillActivityLogTab } from './QuillActivityLogDetails'
import { QuillActivityLogRowBody } from './QuillActivityLogRowBody'
import { useCopyActivityLink } from './useCopyActivityLink'

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

/** Quill sibling of `ActivityLogRow`, for the activity side panel and the quill History page. */
export function QuillActivityLogRow({
    logItem,
    highlighted,
    actions,
}: {
    logItem: HumanizedActivityLogItem
    /** Scrolls the row into view and opens it, for a link to one activity. */
    highlighted?: boolean
    /** Extra buttons for the row, shown before its link button. */
    actions?: JSX.Element | null
}): JSX.Element {
    const [expanded, setExpanded] = useState(false)
    const [activeTab, setActiveTab] = useState<QuillActivityLogTab>(logItem.expandedView ? 'details' : 'diff')
    const detailsId = useId()
    const rowRef = useRef<HTMLDivElement>(null)
    const copyLink = useCopyActivityLink(logItem.id)

    useEffect(() => {
        if (highlighted && rowRef.current) {
            rowRef.current.scrollIntoView({ behavior: 'smooth', block: 'center' })
            setExpanded(true)
        }
    }, [highlighted])

    return (
        <div
            ref={rowRef}
            className={clsx(
                'group/activity flex flex-col rounded-md text-xs',
                expanded && 'border border-border',
                logItem.unread && 'bg-fill-selected',
                highlighted && 'ActivityLogRow--highlighted'
            )}
        >
            <div className="flex gap-2 p-2">
                <QuillActivityLogActor logItem={logItem} />
                <QuillActivityLogRowBody logItem={logItem} expanded={expanded} />
                <div className="flex shrink-0 items-start gap-0.5">
                    {actions}
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
                <QuillActivityLogDetails
                    logItem={logItem}
                    detailsId={detailsId}
                    activeTab={activeTab}
                    onTabChange={setActiveTab}
                />
            )}
        </div>
    )
}
