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
