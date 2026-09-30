import { useActions, useValues } from 'kea'

import { Link } from 'lib/lemon-ui/Link'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'
import { urls } from 'scenes/urls'

import type { BriefingSegmentApi } from 'products/today/frontend/generated/api.schemas'

import { isExternalHref, itemHref } from './todayBriefingItems'
import { todayLogic } from './todayLogic'

function PersonalBriefingSegment({ segment }: { segment: BriefingSegmentApi }): JSX.Element {
    const { briefingItems, hoveredItemKey } = useValues(todayLogic)
    const { itemOpened, setHoveredItemKey } = useActions(todayLogic)
    const item = segment.item_key ? briefingItems.find((candidate) => candidate.key === segment.item_key) : undefined
    if (!item) {
        return <span>{segment.text}</span>
    }
    const href = itemHref(item)
    const link = (
        <Link
            to={href}
            target={isExternalHref(href) ? '_blank' : undefined}
            subtle
            className="TodayReportLink"
            data-active={hoveredItemKey === item.key}
            data-done={item.state === 'done'}
            data-attr="today-briefing-item"
            onClick={() => itemOpened(item, 'briefing')}
            onMouseEnter={() => setHoveredItemKey(item.key)}
            onMouseLeave={() => setHoveredItemKey(null)}
        >
            {segment.text}
        </Link>
    )
    return segment.highlight ? <span className="TodayHome__highlight">{link}</span> : link
}

export function TodayPersonalBriefing(): JSX.Element | null {
    const { personalBriefing } = useValues(todayLogic)
    const { askSidePanelMax } = useActions(maxGlobalLogic)

    if (!personalBriefing) {
        return null
    }
    if (personalBriefing.items.length === 0) {
        return (
            <>
                <p className="TodayHome__count">{personalBriefing.headline || 'Nothing needs you right now'}</p>
                <p>
                    <span>
                        Reports assigned to you, changes on dashboards you use, firing alerts, your tickets and your
                        pull requests show up here. Your briefing updates at 8:00 and at noon.{' '}
                    </span>
                    <Link to={urls.inbox()} data-attr="today-empty-briefing-inbox">
                        Open the Inbox
                    </Link>
                    <span> to see every report.</span>
                </p>
            </>
        )
    }
    const moreCount = personalBriefing.more_reports_count

    return (
        <>
            <p className="TodayHome__count">{personalBriefing.headline}</p>
            {personalBriefing.paragraphs.map((paragraph, index) => (
                <p key={index}>
                    {paragraph.map((segment, segmentIndex) => (
                        <PersonalBriefingSegment key={segmentIndex} segment={segment} />
                    ))}
                </p>
            ))}
            <p className="TodayHome__foot">
                {moreCount > 0 && (
                    <>
                        <Link to={urls.inbox()} data-attr="today-briefing-inbox">
                            {`${moreCount} more for you in the Inbox`}
                        </Link>
                        <span>. </span>
                    </>
                )}
                <span>Or </span>
                <button
                    type="button"
                    data-attr="today-ask-about-edition"
                    onClick={() => askSidePanelMax('Walk me through what changed in my product today.')}
                >
                    ask PostHog AI to walk you through it
                </button>
                <span>.</span>
            </p>
        </>
    )
}
