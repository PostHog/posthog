import { Card, Text } from '@posthog/quill'

// A pinned table column matches the card, and shows its edge only while the table is scrolled under it.
const TABLE_BODY_CLASS =
    '[--quill-table-sticky-bg:var(--card)] [&_[data-sticky=right]]:border-l-transparent [&_[data-scroll-right]_[data-sticky=right]]:border-l-[var(--border)]'

export interface WarehouseSectionProps {
    title: string
    /** One muted line under the title. */
    description?: React.ReactNode
    /** Right-aligned in the header row. Wraps below the title in a narrow container. */
    controls?: React.ReactNode
    /** The body is a table: it runs edge to edge under a divider. */
    flush?: boolean
    children: React.ReactNode
    'data-attr'?: string
}

/** The one card of the console pages: a header row with title, description and controls, then the body. */
export function WarehouseSection({
    title,
    description,
    controls,
    flush = false,
    children,
    'data-attr': dataAttr,
}: WarehouseSectionProps): JSX.Element {
    return (
        <Card size="sm" data-attr={dataAttr}>
            <div
                className={
                    flush
                        ? 'flex flex-wrap items-start justify-between gap-x-3 gap-y-2 border-b px-3 pb-3'
                        : 'flex flex-wrap items-start justify-between gap-x-3 gap-y-2 px-3'
                }
            >
                <div className="min-w-0">
                    <Text size="sm" weight="semibold" render={<h3 className="m-0" />}>
                        {title}
                    </Text>
                    {description ? (
                        <Text size="xs" variant="muted" render={<div />}>
                            {description}
                        </Text>
                    ) : null}
                </div>
                {controls ? <div className="flex flex-wrap items-center gap-2">{controls}</div> : null}
            </div>
            <div className={flush ? TABLE_BODY_CLASS : 'px-3'}>{children}</div>
        </Card>
    )
}
