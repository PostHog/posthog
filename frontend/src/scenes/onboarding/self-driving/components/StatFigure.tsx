/** A big figure with a small caption — the pricing headline's number pairs. */
export function StatFigure({ value, label }: { value: string | number; label: string }): JSX.Element {
    return (
        <div>
            <p className="m-0 text-2xl font-bold leading-tight">{value}</p>
            <p className="m-0 text-xs text-muted">{label}</p>
        </div>
    )
}
