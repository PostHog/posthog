// Ported from https://github.com/its-danny/use-lilius
import {
    addMonths,
    addYears,
    eachDayOfInterval,
    eachMonthOfInterval,
    eachWeekOfInterval,
    endOfMonth,
    endOfWeek,
    isAfter,
    isBefore,
    isEqual,
    set,
    setMonth,
    setYear,
    startOfMonth,
    startOfToday,
    startOfWeek,
    subMonths,
    subYears,
} from 'date-fns'
import { useCallback, useMemo, useState } from 'react'

export const Month = {
    JANUARY: 0,
    FEBRUARY: 1,
    MARCH: 2,
    APRIL: 3,
    MAY: 4,
    JUNE: 5,
    JULY: 6,
    AUGUST: 7,
    SEPTEMBER: 8,
    OCTOBER: 9,
    NOVEMBER: 10,
    DECEMBER: 11,
} as const
export type Month = (typeof Month)[keyof typeof Month]

export const Day = {
    SUNDAY: 0,
    MONDAY: 1,
    TUESDAY: 2,
    WEDNESDAY: 3,
    THURSDAY: 4,
    FRIDAY: 5,
    SATURDAY: 6,
} as const
export type Day = (typeof Day)[keyof typeof Day]

export interface UseCalendarOptions {
    weekStartsOn?: Day
    viewing?: Date
    selected?: Date[]
    numberOfMonths?: number
}

export interface UseCalendarReturn {
    clearTime: (date: Date) => Date
    inRange: (date: Date, min: Date, max: Date) => boolean
    viewing: Date
    setViewing: React.Dispatch<React.SetStateAction<Date>>
    viewToday: () => void
    viewMonth: (month: Month) => void
    viewPreviousMonth: () => void
    viewNextMonth: () => void
    viewYear: (year: number) => void
    viewPreviousYear: () => void
    viewNextYear: () => void
    selected: Date[]
    setSelected: React.Dispatch<React.SetStateAction<Date[]>>
    clearSelected: () => void
    isSelected: (date: Date) => boolean
    select: (date: Date | Date[], replaceExisting?: boolean) => void
    deselect: (date: Date | Date[]) => void
    toggle: (date: Date, replaceExisting?: boolean) => void
    selectRange: (start: Date, end: Date, replaceExisting?: boolean) => void
    deselectRange: (start: Date, end: Date) => void
    calendar: Date[][][]
}

const inRange = (date: Date, min: Date, max: Date): boolean =>
    (isEqual(date, min) || isAfter(date, min)) && (isEqual(date, max) || isBefore(date, max))

const clearTime = (date: Date): Date => set(date, { hours: 0, minutes: 0, seconds: 0, milliseconds: 0 })

export const useCalendar = ({
    weekStartsOn = Day.SUNDAY,
    viewing: initialViewing = new Date(),
    selected: initialSelected = [],
    numberOfMonths = 1,
}: UseCalendarOptions = {}): UseCalendarReturn => {
    const [viewing, setViewing] = useState<Date>(initialViewing)

    const viewToday = useCallback(() => setViewing(startOfToday()), [])
    const viewMonth = useCallback((month: Month) => setViewing((v) => setMonth(v, month)), [])
    const viewPreviousMonth = useCallback(() => setViewing((v) => subMonths(v, 1)), [])
    const viewNextMonth = useCallback(() => setViewing((v) => addMonths(v, 1)), [])
    const viewYear = useCallback((year: number) => setViewing((v) => setYear(v, year)), [])
    const viewPreviousYear = useCallback(() => setViewing((v) => subYears(v, 1)), [])
    const viewNextYear = useCallback(() => setViewing((v) => addYears(v, 1)), [])

    const [selected, setSelected] = useState<Date[]>(initialSelected.map(clearTime))

    const clearSelected = useCallback(() => setSelected([]), [])

    const isSelected = useCallback(
        (date: Date) => selected.findIndex((s) => isEqual(s, date)) > -1,
        [selected]
    )

    const select = useCallback((date: Date | Date[], replaceExisting?: boolean) => {
        if (replaceExisting) {
            setSelected(Array.isArray(date) ? date : [date])
        } else {
            setSelected((items) => items.concat(Array.isArray(date) ? date : [date]))
        }
    }, [])

    const deselect = useCallback(
        (date: Date | Date[]) =>
            setSelected((items) =>
                Array.isArray(date)
                    ? items.filter((s) => !date.map((d) => d.getTime()).includes(s.getTime()))
                    : items.filter((s) => !isEqual(s, date))
            ),
        []
    )

    const toggle = useCallback(
        (date: Date, replaceExisting?: boolean) =>
            isSelected(date) ? deselect(date) : select(date, replaceExisting),
        [deselect, isSelected, select]
    )

    const selectRange = useCallback((start: Date, end: Date, replaceExisting?: boolean) => {
        if (replaceExisting) {
            setSelected(eachDayOfInterval({ start, end }))
        } else {
            setSelected((items) => items.concat(eachDayOfInterval({ start, end })))
        }
    }, [])

    const deselectRange = useCallback((start: Date, end: Date) => {
        setSelected((items) =>
            items.filter((s) => !eachDayOfInterval({ start, end }).map((d) => d.getTime()).includes(s.getTime()))
        )
    }, [])

    const calendar = useMemo<Date[][][]>(
        () =>
            eachMonthOfInterval({
                start: startOfMonth(viewing),
                end: endOfMonth(addMonths(viewing, numberOfMonths - 1)),
            }).map((month) =>
                eachWeekOfInterval(
                    {
                        start: startOfMonth(month),
                        end: endOfMonth(month),
                    },
                    { weekStartsOn }
                ).map((week) =>
                    eachDayOfInterval({
                        start: startOfWeek(week, { weekStartsOn }),
                        end: endOfWeek(week, { weekStartsOn }),
                    })
                )
            ),
        [viewing, weekStartsOn, numberOfMonths]
    )

    return {
        clearTime,
        inRange,
        viewing,
        setViewing,
        viewToday,
        viewMonth,
        viewPreviousMonth,
        viewNextMonth,
        viewYear,
        viewPreviousYear,
        viewNextYear,
        selected,
        setSelected,
        clearSelected,
        isSelected,
        select,
        deselect,
        toggle,
        selectRange,
        deselectRange,
        calendar,
    }
}
