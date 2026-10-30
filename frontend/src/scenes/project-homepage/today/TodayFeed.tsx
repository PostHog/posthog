import './TodayFeed.scss'

import { useActions, useValues } from 'kea'

import { TodayFeedHighlightCard } from './TodayFeedHighlightCard'
import { TodayFeedReportCard } from './TodayFeedReportCard'
import { TodayFeedSources } from './TodayFeedSources'
import { feedCardEvent } from './todayFeedText'
import { todayLogic } from './todayLogic'

export function TodayFeed(): JSX.Element {
    const { feedRows, forYouCanShowMore } = useValues(todayLogic)
    const { feedCardHovered, feedCardClicked } = useActions(todayLogic)
    return (
        <div className="TodayFeed">
            <div className="min-w-0">
                <ol className="TodayFeed__posts">
                    {feedRows.map((row, index) => {
                        const event = feedCardEvent(row, index)
                        const tracking = {
                            onDwell: () => feedCardHovered(event),
                            onInteract: (target: string) => feedCardClicked(event, target),
                        }
                        return row.kind === 'report' ? (
                            <TodayFeedReportCard
                                key={row.key}
                                report={row.report}
                                source={row.source}
                                done={row.done}
                                tracking={tracking}
                            />
                        ) : (
                            <TodayFeedHighlightCard
                                key={row.key}
                                item={row.item}
                                position={row.position}
                                done={row.done}
                                tracking={tracking}
                            />
                        )
                    })}
                </ol>
                {!forYouCanShowMore && <p className="TodayFeed__end">You’re all caught up</p>}
            </div>
            <TodayFeedSources />
        </div>
    )
}
