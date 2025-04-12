import { LemonSkeleton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { TZLabel } from 'lib/components/TZLabel'
import { Dayjs } from 'lib/dayjs'
import { MouseEvent, useCallback } from 'react'
import { match, P } from 'ts-pattern'

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
        <>
            {match([loading, time])
                .with([true, P.any], () => <LemonSkeleton className="w-[50px] h-2" />)
                .with([false, P.nullish], () => <span className="text-xs text-muted">-</span>)
                .with([false, P.any], () => (
                    <span
                        onClick={onClick}
                        className="hover:bg-fill-button-tertiary-hover px-1 rounded flex items-center"
                    >
                        <TZLabel
                            time={time as Dayjs}
                            className="border-dotted border-b text-xs text-muted"
                            title={label}
                        />
                    </span>
                ))
                .exhaustive()}
        </>
    )
}
