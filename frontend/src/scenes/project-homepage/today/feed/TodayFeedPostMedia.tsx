import { useActions, useValues } from 'kea'

import { ReportChartCard } from 'products/signals/frontend/inbox/components/detail/ReportChart'

import { TodayFeedCard } from './TodayFeedCard'
import { TodayFeedChart } from './TodayFeedChart'
import type { TodayFeedPost } from './todayFeedItems'
import { todayFeedLogic } from './todayFeedLogic'
import { TodayFeedReplay } from './TodayFeedReplay'

export function TodayFeedPostMedia({ post, position }: { post: TodayFeedPost; position: number }): JSX.Element | null {
    const { enrolledFlagKeys } = useValues(todayFeedLogic)
    const { postOpened, postEnrolled, postPlayed } = useActions(todayFeedLogic)
    const open = (): void => postOpened(post, position)
    const { media } = post

    switch (media?.type) {
        case 'chart':
            return (
                <TodayFeedChart
                    label={media.label}
                    current={media.current}
                    previous={media.previous}
                    series={media.series}
                    days={media.days}
                    to={post.to}
                    onOpen={open}
                />
            )
        case 'report-chart':
            return <ReportChartCard chart={media.chart} />
        case 'replay':
            return (
                <TodayFeedReplay
                    sessionId={media.sessionId}
                    page={media.page}
                    caption={media.caption}
                    to={post.to}
                    onPlay={() => postPlayed(post, position)}
                    onOpen={open}
                />
            )
        case 'card':
            return (
                <TodayFeedCard
                    title={media.title}
                    description={media.description}
                    actionLabel={media.actionLabel}
                    to={post.to}
                    onOpen={open}
                    onEnroll={media.enrollFlagKey ? () => postEnrolled(post, position) : undefined}
                    enrolled={!!media.enrollFlagKey && !!enrolledFlagKeys[media.enrollFlagKey]}
                />
            )
        default:
            return null
    }
}
