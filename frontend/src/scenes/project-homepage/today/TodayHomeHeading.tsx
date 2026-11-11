export function TodayHomeHeading({
    id,
    count,
    children,
}: {
    id?: string
    count?: number
    children: string
}): JSX.Element {
    return (
        <h2 id={id} className="TodayHome__heading">
            <span>{children}</span>
            {count ? (
                <span className="TodayHome__headingCount" translate="no">
                    {count}
                </span>
            ) : null}
        </h2>
    )
}
