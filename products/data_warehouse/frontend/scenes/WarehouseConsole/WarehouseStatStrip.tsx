/** The row of `WarehouseStatTile`s at the top of a console page: 4-up wide, 2-up at medium, 1-up narrow. */
export function WarehouseStatStrip({
    children,
    maxColumns = 4,
    'data-attr': dataAttr,
}: {
    children: React.ReactNode
    /** Use 2 for a strip of two or three tiles, so they do not shrink to a quarter each. */
    maxColumns?: 2 | 4
    'data-attr'?: string
}): JSX.Element {
    return (
        <div
            className={
                maxColumns === 2
                    ? 'grid grid-cols-1 items-stretch gap-3 @xl:grid-cols-2'
                    : 'grid grid-cols-1 items-stretch gap-3 @xl:grid-cols-2 @4xl:grid-cols-4'
            }
            data-attr={dataAttr}
        >
            {children}
        </div>
    )
}
