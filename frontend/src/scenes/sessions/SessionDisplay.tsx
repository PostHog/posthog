import { router } from 'kea-router'
import { useState } from 'react'

import { Tooltip } from '@posthog/lemon-ui'

import { Link } from 'lib/lemon-ui/Link'
import { Popover } from 'lib/lemon-ui/Popover'
import { useNotebookNode } from 'scenes/notebooks/Nodes/NotebookNodeContext'
import { urls } from 'scenes/urls'

import { SessionPreview } from './SessionPreview'

export interface SessionDisplayProps {
    sessionId: string
    isLive?: boolean
    noPopover?: boolean
    noLink?: boolean
    placement?: 'top' | 'bottom' | 'left' | 'right'
}

export function SessionDisplay({ sessionId, isLive, noPopover, noLink, placement }: SessionDisplayProps): JSX.Element {
    const [visible, setVisible] = useState(false)
    const notebookNode = useNotebookNode()
    const href = urls.sessionProfile(sessionId)

    const handleClick = (e: React.MouseEvent): void => {
        if (visible && href && !noLink) {
            router.actions.push(href)
        } else {
            setVisible(true)
        }
        e.preventDefault()
    }

    const liveIndicator = isLive ? (
        <Tooltip title="Live session">
            <span className="relative flex h-2.5 w-2.5 shrink-0">
                <span
                    className="absolute inline-flex h-full w-full rounded-full bg-danger animate-ping"
                    style={{ opacity: 0.75 }}
                />
                <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-danger" />
            </span>
        </Tooltip>
    ) : (
        <span className="relative flex h-2.5 w-2.5 shrink-0" />
    )

    const content = (
        <div className="flex flex-row items-center gap-2">
            {liveIndicator}
            {noLink || !href ? (
                <span className="font-mono">{sessionId}</span>
            ) : (
                <Link
                    to={href}
                    onClick={(e: React.MouseEvent): void => {
                        if (!noPopover && !notebookNode) {
                            e.preventDefault()
                        }
                    }}
                    className="font-mono"
                >
                    {sessionId}
                </Link>
            )}
        </div>
    )

    if (noPopover || notebookNode) {
        return content
    }

    return (
        <Popover
            overlay={<SessionPreview sessionId={sessionId} onClose={() => setVisible(false)} />}
            visible={visible}
            onClickOutside={() => setVisible(false)}
            placement={placement || 'top'}
            fallbackPlacements={['bottom', 'right']}
            showArrow
        >
            <span onClick={handleClick} className="cursor-pointer">
                {content}
            </span>
        </Popover>
    )
}
