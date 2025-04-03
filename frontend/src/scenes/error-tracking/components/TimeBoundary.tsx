import { LemonSkeleton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { TZLabel } from 'lib/components/TZLabel'
import { Dayjs } from 'lib/dayjs'
import { MouseEvent, useCallback } from 'react'

import { DateRange } from '~/queries/schema/schema-general'

import { errorTrackingIssueSceneLogic } from '../errorTrackingIssueSceneLogic'

type TimeBoundaryProps = {
    label: string
    time: Dayjs | null | undefined
    loading: boolean
    updateDateRange: (dateRange: DateRange) => DateRange
}

export function TimeBoundary({ time, loading, label, updateDateRange }: TimeBoundaryProps): JSX.Element {
    const { dateRange } = useValues(errorTrackingIssueSceneLogic)
    const { setDateRange } = useActions(errorTrackingIssueSceneLogic)
    const onClick = useCallback(
        (e: MouseEvent): void => {
            setDateRange(updateDateRange(dateRange))
            e.preventDefault()
            e.stopPropagation()
        },
        [dateRange, updateDateRange, setDateRange]
    )
    return (
        <div>
            {loading && <LemonSkeleton />}
            {!loading && time && (
                <span onClick={onClick} className="hover:bg-fill-button-tertiary-hover px-1 rounded">
                    <TZLabel time={time} className="border-dotted border-b text-xs text-muted" title={label} />
                </span>
            )}
            {!loading && !time && <>-</>}
        </div>
    )
}
