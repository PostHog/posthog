/** The row of `WarehouseStatTile`s at the top of a console page: 4-up wide, 2-up at medium, 1-up narrow. */
export function WarehouseStatStrip({
    children,
    'data-attr': dataAttr,
}: {
    children: React.ReactNode
    'data-attr'?: string
}): JSX.Element {
    return (
        <div className="grid grid-cols-1 items-stretch gap-3 @xl:grid-cols-2 @4xl:grid-cols-4" data-attr={dataAttr}>
            {children}
        </div>
    )
}
