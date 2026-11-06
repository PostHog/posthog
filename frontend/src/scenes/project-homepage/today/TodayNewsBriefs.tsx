const LEADING_NUMBER = /^(\d[\d,.]*%?)\s+(.+)$/

function TodayNewsBrief({ brief }: { brief: string }): JSX.Element {
    const match = LEADING_NUMBER.exec(brief)
    return (
        <li className="flex flex-col gap-1">
            {match ? (
                <span className="text-4xl leading-none font-bold tracking-tighter tabular-nums" translate="no">
                    {match[1]}
                </span>
            ) : null}
            <span className="text-sm text-pretty text-muted-foreground">{match ? match[2] : brief}</span>
        </li>
    )
}

export function TodayNewsBriefs({ briefs }: { briefs: string[] }): JSX.Element {
    const main = briefs.length > 1 ? briefs.slice(0, -1) : briefs
    const side = briefs.length > 1 ? briefs[briefs.length - 1] : null
    return (
        <section className="flex flex-col gap-4 border-t-2 border-foreground pt-3">
            <h4 className="m-0 font-mono text-xs tracking-wide text-muted-foreground uppercase">By the numbers</h4>
            <div className="grid gap-6 @3xl:grid-cols-[5fr_3fr]">
                <ul className="m-0 grid list-none grid-cols-2 gap-6 p-0">
                    {main.map((brief) => (
                        <TodayNewsBrief key={brief} brief={brief} />
                    ))}
                </ul>
                {side ? (
                    <ul className="m-0 list-none p-0 @3xl:border-l @3xl:pl-6">
                        <TodayNewsBrief brief={side} />
                    </ul>
                ) : null}
            </div>
        </section>
    )
}
