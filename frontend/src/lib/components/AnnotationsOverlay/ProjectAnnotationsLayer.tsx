import { BindLogic } from 'kea'
import { useId, useMemo } from 'react'

import { dayjs } from 'lib/dayjs'
import { insightLogic } from 'scenes/insights/insightLogic'

import type { InsightLogicProps, IntervalType } from '~/types'

import { AnnotationsLayer } from './AnnotationsLayer'

const STANDALONE_INSIGHT_PROPS: InsightLogicProps = {
    dashboardItemId: 'new-AdHoc.project-annotations',
    doNotLoad: true,
}

function intervalForBucketDates(dates: string[]): IntervalType {
    if (dates.length < 2) {
        return 'day'
    }
    const bucketSeconds = dayjs(dates[1]).diff(dayjs(dates[0]), 'second')
    if (bucketSeconds < 60) {
        return 'second'
    }
    if (bucketSeconds < 3600) {
        return 'minute'
    }
    return bucketSeconds < 86400 ? 'hour' : 'day'
}

/** Annotations for a quill time series that is not an insight, such as the logs, metrics, and tracing
 *  charts. Shows project- and organization-scoped annotations. Mount it as a child of the chart. */
export function ProjectAnnotationsLayer({ dates }: { dates: string[] }): JSX.Element {
    const kind = useId()
    const interval = useMemo(() => intervalForBucketDates(dates), [dates])

    return (
        <BindLogic logic={insightLogic} props={STANDALONE_INSIGHT_PROPS}>
            <AnnotationsLayer insightNumericId="new" dates={dates} kind={kind} interval={interval} />
        </BindLogic>
    )
}
