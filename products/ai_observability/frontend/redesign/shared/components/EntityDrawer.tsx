import { ReactNode } from 'react'

import { IconX } from '@posthog/icons'
import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { DetailPanel, DetailPanelProps } from './DetailPanel'

export interface EntityDrawerTile {
    label: string
    value: ReactNode
    loading?: boolean
}

export interface EntityDrawerSection {
    title: string
    /** Null leaves the section out. */
    content: ReactNode | null
}

export interface EntityDrawerProps extends Pick<
    DetailPanelProps,
    'rect' | 'width' | 'resizer' | 'containerRef' | 'aria-label' | 'data-attr'
> {
    title: ReactNode
    tag?: ReactNode
    tiles: EntityDrawerTile[]
    chart?: ReactNode
    sections: EntityDrawerSection[]
    footer?: ReactNode
    onClose: () => void
}

function StatTile({ label, value, loading = false }: EntityDrawerTile): JSX.Element {
    return (
        <div className="flex min-w-0 flex-col gap-1 rounded border bg-surface-primary p-3">
            <span className="truncate text-xs font-medium text-secondary">{label}</span>
            {loading ? (
                <LemonSkeleton className="h-7 w-2/3" />
            ) : (
                <span className="break-words text-lg font-semibold tabular-nums">{value}</span>
            )}
        </div>
    )
}

export function EntityDrawer({
    title,
    tag,
    tiles,
    chart,
    sections,
    footer,
    onClose,
    'data-attr': dataAttr,
    ...panelProps
}: EntityDrawerProps): JSX.Element {
    return (
        <DetailPanel
            {...panelProps}
            data-attr={dataAttr}
            toolbar={
                <LemonButton
                    className="ml-auto"
                    size="small"
                    icon={<IconX />}
                    tooltip="Close"
                    aria-label="Close"
                    // pinned: data-attrs feed autocapture; dashboards and tests find the close button by this suffix
                    data-attr={`${dataAttr}-close`}
                    onClick={onClose}
                />
            }
        >
            <div className="flex flex-col gap-4">
                <div className="flex min-w-0 flex-wrap items-baseline gap-2">
                    <h2 className="m-0 min-w-0 break-words text-base font-semibold">{title}</h2>
                    {tag}
                </div>
                {tiles.length > 0 ? (
                    // Each tile keeps a minimum width, and auto-fit drops the empty columns, so a few tiles still fill a wide drawer.
                    <div className="grid grid-cols-[repeat(auto-fit,minmax(8rem,1fr))] gap-2">
                        {tiles.map((tile) => (
                            <StatTile key={tile.label} {...tile} />
                        ))}
                    </div>
                ) : null}
                {chart}
                {sections.map(({ title: sectionTitle, content }) =>
                    content === null ? null : (
                        <section key={sectionTitle} className="flex flex-col gap-2">
                            <h3 className="m-0 text-sm font-semibold">{sectionTitle}</h3>
                            {content}
                        </section>
                    )
                )}
                {footer ? <div className="flex flex-wrap items-center gap-2">{footer}</div> : null}
            </div>
        </DetailPanel>
    )
}
