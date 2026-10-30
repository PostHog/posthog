import { useActions, useValues } from 'kea'
import { Suspense, lazy, useId } from 'react'

import { IconHide } from '@posthog/icons'
import { Button, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { retryImport } from 'lib/utils/retryImport'

import { todayFeedLogic } from './todayFeedLogic'
import { TodayHomeHeading } from './TodayHomeHeading'
import { TodayRow } from './TodayRow'
import { feedIcon } from './todayRowIcons'
import { TodayRowsSkeleton } from './TodayRowsSkeleton'

const TodaySparkline = lazy(() =>
    retryImport(() => import('./TodaySparkline').then((m) => ({ default: m.TodaySparkline })))
)

export function TodayFeed(): JSX.Element {
    const { feedItems, feedReady } = useValues(todayFeedLogic)
    const { cardOpened, cardHidden } = useActions(todayFeedLogic)
    const titleId = useId()

    return (
        <section className="TodayHome__list" aria-labelledby={titleId}>
            <div className="TodayHome__headingRow">
                <TodayHomeHeading id={titleId}>Worth a look</TodayHomeHeading>
            </div>
            {!feedReady ? (
                <TodayRowsSkeleton />
            ) : feedItems.length === 0 ? (
                <p className="TodayHome__note">
                    Nothing new to show yet. Big changes in your events and sessions worth watching show up here.
                </p>
            ) : (
                <>
                    <ol className="TodayRows">
                        {feedItems.map((item, position) => (
                            <TodayRow
                                key={item.key}
                                tone="neutral"
                                icon={feedIcon(item)}
                                title={item.title}
                                label={item.label}
                                facts={item.facts}
                                to={item.to}
                                onOpen={() => cardOpened(item, position)}
                                aside={
                                    item.series && item.seriesLabels ? (
                                        <span className="TodayFeed__spark" aria-hidden>
                                            <Suspense fallback={null}>
                                                <TodaySparkline
                                                    values={item.series}
                                                    labels={item.seriesLabels}
                                                    emphasizeLast={7}
                                                    tone="neutral"
                                                />
                                            </Suspense>
                                        </span>
                                    ) : undefined
                                }
                                actions={
                                    <Tooltip>
                                        <TooltipTrigger
                                            render={
                                                <Button
                                                    variant="link-muted"
                                                    size="icon-sm"
                                                    aria-label="Hide"
                                                    onClick={() => cardHidden(item, position)}
                                                    data-attr="today-feed-hide"
                                                />
                                            }
                                        >
                                            <IconHide className="size-3.5" />
                                        </TooltipTrigger>
                                        <TooltipContent side="bottom">Hide</TooltipContent>
                                    </Tooltip>
                                }
                                dataAttr="today-feed-card"
                            />
                        ))}
                    </ol>
                    <p className="TodayHome__note">That is everything for today.</p>
                </>
            )}
        </section>
    )
}
