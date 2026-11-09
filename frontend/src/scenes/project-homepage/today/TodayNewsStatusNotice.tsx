import { useValues } from 'kea'

import { Spinner, Text } from '@posthog/quill'

import { ElapsedTime } from 'scenes/experiments/MetricsView/new/ElapsedTime'

import { todayNewsLogic } from './todayNewsLogic'

export function TodayNewsStatusNotice(): JSX.Element | null {
    const { newsStatus, edition, writingSince, isWriteUnavailable } = useValues(todayNewsLogic)

    if (newsStatus === 'computing') {
        return (
            <div className="flex items-start gap-2 border-b px-4 py-3">
                <Spinner aria-hidden className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
                <span role="status" className="flex flex-col gap-0.5">
                    <Text size="xs" render={<span />}>
                        Writing today's news. This takes a few minutes.
                    </Text>
                    {edition ? (
                        <Text size="xs" variant="muted" render={<span />}>
                            Until then, here is the latest edition.
                        </Text>
                    ) : null}
                </span>
                <Text size="xs" variant="muted" render={<span />} className="ms-auto shrink-0 tabular-nums">
                    <ElapsedTime startTime={writingSince} />
                </Text>
            </div>
        )
    }
    if (newsStatus === 'failed') {
        return (
            <div role="status" className="border-b px-4 py-3">
                <Text size="xs" render={<p />} className="m-0">
                    {edition
                        ? "Couldn't write today's news. Here is the latest edition."
                        : "Couldn't write today's news. Check back later."}
                </Text>
            </div>
        )
    }
    if (newsStatus === 'not_started' && isWriteUnavailable) {
        return (
            <div role="status" className="border-b px-4 py-3">
                <Text size="xs" render={<p />} className="m-0">
                    {edition
                        ? "Today's news isn't available yet. Here is the latest edition."
                        : "Today's news isn't available yet. Check back later."}
                </Text>
            </div>
        )
    }
    return null
}
