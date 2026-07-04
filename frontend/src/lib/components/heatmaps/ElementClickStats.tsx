import { IconCalendar } from '@posthog/icons'

type ElementStatisticProps = {
    title: string
    value: string | number
    prefix?: string
    suffix?: string
}

export function ElementStatistic({ title, value, prefix, suffix }: ElementStatisticProps): JSX.Element {
    return (
        <div className="flex flex-col">
            <div>{title}</div>
            <div className="text-2xl">
                {prefix}
                {value}
                {suffix}
            </div>
        </div>
    )
}

export interface ElementClickStatsProps {
    count: number
    totalCount: number
    rank?: number
    clickCount?: number
    rageclickCount?: number
    deadclickCount?: number
    dateRange?: string | JSX.Element
}

export function ElementClickStats({
    count,
    totalCount,
    rank,
    clickCount,
    rageclickCount,
    deadclickCount,
    dateRange,
}: ElementClickStatsProps): JSX.Element {
    return (
        <>
            {dateRange ? (
                <p>
                    <IconCalendar /> <u>{dateRange}</u>
                </p>
            ) : null}
            <div className="grid grid-cols-[auto_1fr] gap-4">
                <ElementStatistic
                    title="Clicks"
                    value={count}
                    suffix={`/${totalCount} (${
                        totalCount === 0 ? '?' : Math.round((count / totalCount) * 10000) / 100
                    }%)`}
                />
                {rank !== undefined ? <ElementStatistic title="Ranking" prefix="#" value={rank} /> : null}
                {clickCount !== undefined ? <ElementStatistic title="Autocapture clicks" value={clickCount} /> : null}
                {rageclickCount !== undefined ? <ElementStatistic title="Rageclicks" value={rageclickCount} /> : null}
                {deadclickCount !== undefined ? <ElementStatistic title="Deadclicks" value={deadclickCount} /> : null}
            </div>
        </>
    )
}
