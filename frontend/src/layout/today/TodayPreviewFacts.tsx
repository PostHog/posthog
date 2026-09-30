export interface TodayPreviewFact {
    label: string
    value: string | null
}

/** The label and value pairs at the foot of a hover card. A fact with no value is left out. */
export function TodayPreviewFacts({ facts }: { facts: TodayPreviewFact[] }): JSX.Element | null {
    const shown = facts.filter((fact) => fact.value)
    if (shown.length === 0) {
        return null
    }
    return (
        <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1 text-xs">
            {shown.map((fact) => (
                <div key={fact.label} className="contents">
                    <dt className="text-muted-foreground">{fact.label}</dt>
                    <dd className="m-0 text-foreground wrap-anywhere">{fact.value}</dd>
                </div>
            ))}
        </dl>
    )
}
