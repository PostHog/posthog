export function ExclusionRow({
    seriesIndicator,
    filter,
    suffix,
    isVertical,
}: {
    seriesIndicator?: JSX.Element | string
    suffix?: JSX.Element | string
    filter?: JSX.Element | string
    isVertical?: boolean
}): JSX.Element {
    if (isVertical) {
        return (
            <div className="w-full">
                <div className="flex flex-nowrap items-center">
                    <div className="px-2">{seriesIndicator}</div>
                    <div className="flex-1">{filter}</div>
                </div>
                <div className="ml-9">{suffix}</div>
            </div>
        )
    }

    return (
        <div className="flex items-center w-full">
            <div className="px-2">{seriesIndicator}</div>
            <div className="flex-1">{filter}</div>
            {suffix}
        </div>
    )
}
