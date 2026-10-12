import { useActions, useValues } from 'kea'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { TodayPreviewTrigger } from '~/layout/today/TodayPreviewTrigger'

import type { BriefingSegmentApi } from 'products/today/frontend/generated/api.schemas'

import { WALK_THROUGH_QUESTION } from './todayAskPrompt'
import { isExternalHref, itemHref, itemSource } from './todayBriefingItems'
import { TodayChipStack } from './TodayChipStack'
import { TodayIcon } from './TodayIcon'
import { todayLogic } from './todayLogic'

function PersonalBriefingSegment({ segment }: { segment: BriefingSegmentApi }): JSX.Element {
    const { briefingItems, reportPreviews, hoveredItemKey } = useValues(todayLogic)
    const { itemOpened, setHoveredItemKey } = useActions(todayLogic)
    const item = segment.item_key ? briefingItems.find((candidate) => candidate.key === segment.item_key) : undefined
    if (!item) {
        return <span>{segment.text}</span>
    }
    const href = itemHref(item)
    const link = (
        <LinkPrimitive
            to={href}
            target={isExternalHref(href) ? '_blank' : undefined}
            className="TodayInlineLink"
            data-active={hoveredItemKey === item.key}
            data-state={item.state}
            data-attr="today-briefing-item"
            onClick={() => itemOpened(item, 'briefing')}
            onMouseEnter={() => setHoveredItemKey(item.key)}
            onMouseLeave={() => setHoveredItemKey(null)}
        >
            {segment.text}
        </LinkPrimitive>
    )
    const preview = reportPreviews.briefing[item.key]
    const linkWithCard = preview ? (
        <TodayPreviewTrigger payload={preview} inline>
            {link}
        </TodayPreviewTrigger>
    ) : (
        link
    )
    return segment.highlight ? <span className="TodayHome__highlight">{linkWithCard}</span> : linkWithCard
}

function PersonalBriefingChips(): JSX.Element | null {
    const { briefingItems, hoveredItemKey } = useValues(todayLogic)
    const { openItem, setHoveredItemKey } = useActions(todayLogic)
    return (
        <TodayChipStack
            dataAttr="today-briefing-item-chip"
            chips={briefingItems.map((item) => {
                const source = itemSource(item)
                return {
                    key: item.key,
                    label: item.label,
                    color: source.color,
                    icon: <TodayIcon icon={source.icon} />,
                    active: hoveredItemKey === item.key,
                    onClick: () => openItem(item, 'chip'),
                    onHoverChange: (hovered) => setHoveredItemKey(hovered ? item.key : null),
                }
            })}
        />
    )
}

export function TodayPersonalBriefing(): JSX.Element | null {
    const { personalBriefing, inboxMore, briefingProgress } = useValues(todayLogic)
    const { askAi } = useActions(todayLogic)

    if (!personalBriefing) {
        return null
    }
    if (personalBriefing.items.length === 0) {
        return (
            <>
                <p className="TodayHome__count">{personalBriefing.headline || 'Nothing needs you right now'}</p>
                <p>
                    <span>
                        Reports that wait for you, that you claimed or review, and urgent reports nobody owns show up
                        here. Your briefing updates every morning at 8:00.{' '}
                    </span>
                    <LinkPrimitive to={urls.inbox()} className="TodayInboxLink" data-attr="today-empty-briefing-inbox">
                        Open the Inbox
                    </LinkPrimitive>
                    <span> to see every report.</span>
                </p>
            </>
        )
    }
    return (
        <>
            <p className="TodayHome__count">
                <span>{personalBriefing.headline}</span>
                <PersonalBriefingChips />
            </p>
            {briefingProgress && (
                <p className="TodayHome__progress" data-attr="today-briefing-progress">
                    {`${briefingProgress.done} of ${briefingProgress.total} done`}
                </p>
            )}
            {personalBriefing.paragraphs.map((paragraph, index) => (
                <p key={index}>
                    {paragraph.map((segment, segmentIndex) => (
                        <PersonalBriefingSegment key={segmentIndex} segment={segment} />
                    ))}
                </p>
            ))}
            <p className="TodayHome__foot">
                {inboxMore && (
                    <>
                        <LinkPrimitive to={urls.inbox()} className="TodayInboxLink" data-attr="today-briefing-inbox">
                            {inboxMore.scope === 'for_you'
                                ? `${inboxMore.count} more for you in the Inbox`
                                : `${inboxMore.count} other open ${pluralize(inboxMore.count, 'report', undefined, false)} in the Inbox`}
                        </LinkPrimitive>
                        <span>. </span>
                    </>
                )}
                <span>Or </span>
                <button
                    type="button"
                    className="TodayInlineAction"
                    data-attr="today-ask-about-edition"
                    onClick={() => askAi(WALK_THROUGH_QUESTION, 'walk_through')}
                >
                    ask PostHog AI to walk you through it
                </button>
                <span>.</span>
            </p>
        </>
    )
}
