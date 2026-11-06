const LEADING_NUMBER = /^(\d[\d,.]*%?)\s+(.+)$/

export function TodayNewsBriefs({ briefs }: { briefs: string[] }): JSX.Element {
    return (
        <section className="flex flex-col gap-3 border-t-2 border-foreground pt-3">
            <h4 className="m-0 font-mono text-xs tracking-wide text-muted-foreground uppercase">By the numbers</h4>
            <ul className="m-0 grid list-none gap-x-6 gap-y-4 p-0 @2xl:grid-cols-3">
                {briefs.map((brief) => {
                    const match = LEADING_NUMBER.exec(brief)
                    return (
                        <li key={brief} className="flex flex-col gap-1">
                            {match ? (
                                <span
                                    className="text-4xl leading-none font-bold tracking-tighter tabular-nums"
                                    translate="no"
                                >
                                    {match[1]}
                                </span>
                            ) : null}
                            <span className="text-sm text-pretty text-muted-foreground">
                                {match ? match[2] : brief}
                            </span>
                        </li>
                    )
                })}
            </ul>
        </section>
    )
}
