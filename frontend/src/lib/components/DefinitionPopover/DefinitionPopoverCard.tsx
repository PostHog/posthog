export function DefinitionPopoverCard({
    title,
    value,
    alignItems = 'baseline',
}: {
    title: string | JSX.Element
    value: React.ReactNode | null
    alignItems?: 'baseline' | 'center' | 'end'
}): JSX.Element {
    return (
        <div
            className="definition-popover-grid-card"
            // eslint-disable-next-line react/forbid-dom-props
            style={{ alignItems }}
        >
            <div className="definition-popover-grid-card-title">{title}</div>
            {value && <div className="definition-popover-grid-card-content">{value}</div>}
        </div>
    )
}
