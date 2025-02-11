import { IconInfo } from '@posthog/icons'
import { LemonSkeleton, Link, Tooltip } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useValues } from 'kea'
import { TZLabel } from 'lib/components/TZLabel'
import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { humanFriendlyLargeNumber } from 'lib/utils'
import { useEffect, useRef, useState } from 'react'
import { errorTrackingIssueSceneLogic } from 'scenes/error-tracking/errorTrackingIssueSceneLogic'

export const Metadata = (): JSX.Element => {
    const { issue } = useValues(errorTrackingIssueSceneLogic)

    const hasSessionCount = issue && issue.aggregations && issue.aggregations.sessions !== 0

    const Count = ({ value }: { value: number | undefined }): JSX.Element => {
        return issue && issue.aggregations ? (
            <div className="text-2xl font-semibold">{value ? humanFriendlyLargeNumber(value) : '-'}</div>
        ) : (
            <div className="flex flex-1 items-center">
                <LemonSkeleton />
            </div>
        )
    }

    const Sessions = (
        <div className="flex flex-col flex-1">
            <div className="flex text-muted text-xs space-x-px">
                <span>Sessions</span>
                {!hasSessionCount && <IconInfo className="mt-0.5" />}
            </div>
            <Count value={issue?.aggregations?.sessions} />
        </div>
    )

    return (
        <div className="space-y-1">
            {issue && issue.description ? (
                <ClampedText
                    text={
                        "THis is some really long text that I don't want to have to writeTHis is some really long text that I don't want to have to writeTHis is some really long text that I don't want to have to writeTHis is some really long text that I don't want to have to writeTHis"
                    }
                    maxLines={2}
                />
            ) : (
                <LemonSkeleton />
            )}
            <div className="flex flex-1 justify-between">
                <div className="flex items-end space-x-6">
                    <div>
                        <div className="text-muted text-xs">First seen</div>
                        {issue ? (
                            <TZLabel time={issue.first_seen} className="border-dotted border-b" />
                        ) : (
                            <LemonSkeleton />
                        )}
                    </div>
                    <div>
                        <div className="text-muted text-xs">Last seen</div>
                        {issue && issue.last_seen ? (
                            <TZLabel time={issue.last_seen} className="border-dotted border-b" />
                        ) : (
                            <LemonSkeleton />
                        )}
                    </div>
                </div>
                <div className="flex space-x-2 gap-8 items-end">
                    <div className="flex flex-col flex-1">
                        <div className="text-muted text-xs">Occurrences</div>
                        <Count value={issue?.aggregations?.occurrences} />
                    </div>
                    {hasSessionCount ? (
                        Sessions
                    ) : (
                        <Tooltip title="No $session_id was set for any event in this issue" delayMs={0}>
                            {Sessions}
                        </Tooltip>
                    )}
                    <div className="flex flex-col flex-1">
                        <div className="text-muted text-xs">Users</div>
                        <Count value={issue?.aggregations?.users} />
                    </div>
                </div>
            </div>
        </div>
    )
}

const ClampedText = ({ text, maxLines }: { text: string; maxLines: number }): JSX.Element => {
    const [needsClamping, setNeedsClamping] = useState(false)
    const [expanded, setExpanded] = useState(false)
    const textRef = useRef<HTMLDivElement>(null)
    const { height } = useResizeObserver({ ref: textRef })

    useEffect(() => {
        // debugger
        if (textRef.current && height) {
            const computedStyle = window.getComputedStyle(textRef.current)
            const lineHeight = parseInt(computedStyle.lineHeight)
            const maxHeight = maxLines * lineHeight

            const shouldClamp = height > maxHeight
            setNeedsClamping(shouldClamp)

            if (shouldClamp && shouldClamp != needsClamping) {
                setExpanded(false)
            }

            // if (shouldClamp) {
            //     setExpanded(textRef.current.scrollHeight >= maxHeight)
            // } else {
            //     setExpanded(false)
            // }
        }
    }, [text, maxLines, height])

    return (
        <div>
            <div ref={textRef} className={clsx('italic', needsClamping && !expanded ? 'line-clamp-2' : null)}>
                {text}
            </div>
            {needsClamping && <Link onClick={() => setExpanded(!expanded)}>{expanded ? 'See less' : 'See more'}</Link>}
        </div>
    )
}
