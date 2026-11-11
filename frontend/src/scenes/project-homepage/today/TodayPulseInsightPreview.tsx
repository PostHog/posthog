import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { Skeleton, Text } from '@posthog/quill'

import { TodayGlance } from '~/layout/today/TodayGlance'
import { todayObjectGlanceLogic } from '~/layout/today/todayObjectGlanceLogic'

import { todayNumber } from './todayNumbers'

export function TodayPulseInsightPreview({ shortId }: { shortId: string }): JSX.Element {
    const { glanceFor } = useValues(todayObjectGlanceLogic)
    const { showGlance } = useActions(todayObjectGlanceLogic)

    useEffect(() => {
        showGlance('insight', shortId, 'pulse_editor')
    }, [shortId, showGlance])

    const glance = glanceFor('insight', shortId)
    return (
        <div className="flex flex-col gap-2 p-3" data-attr="today-pulse-insight-preview">
            {glance === undefined ? (
                <Skeleton className="h-14 w-full" />
            ) : glance ? (
                <TodayGlance glance={glance} formatNumber={todayNumber} />
            ) : (
                <Text size="xs" variant="muted" render={<p />} className="m-0">
                    No preview for this insight
                </Text>
            )}
        </div>
    )
}
