import { IconChevronDown, IconEllipsis, IconLineGraph } from '@posthog/icons'
import { LemonButton, LemonMenu, LemonMenuItem, LemonSelectOptionLeaf } from '@posthog/lemon-ui'

import { useWindowSize } from 'lib/hooks/useWindowSize'
import { IconOpenInNew, IconTableChart } from 'lib/lemon-ui/icons'
import { cn } from 'lib/utils/css-classes'

import { TileId, TileVisualizationOption } from './common'
import { LearnMorePopover, LearnMorePopoverProps } from './WebAnalyticsDashboard'
import { WebTileOpenInsightProps } from './webTileHeaderHooks'

interface DropdownConfig<T extends string> {
    value: T
    options: LemonSelectOptionLeaf<T>[]
    onChange: (value: T) => void
}

export interface WebTileHeaderProps {
    tileId: TileId
    title?: React.ReactNode
    titlePrefix?: string
    titleDropdown?: DropdownConfig<string>
    /** A second picker after the title, read as "<title> by <breakdown>". */
    breakdownDropdown?: DropdownConfig<string>
    /** Extra classes for the header row, such as dropping its padding inside another toolbar. */
    className?: string
    docs?: LearnMorePopoverProps
    intervalSelector?: {
        node: React.ReactNode
    }
    visualizationToggle?: {
        value: TileVisualizationOption | undefined
        onChange: (value: TileVisualizationOption) => void
    }
    openInsight?: WebTileOpenInsightProps
    /** Omit or leave empty to hide the "More actions" menu. */
    overflowMenuItems?: LemonMenuItem[]
}

function TitleDropdown({
    tileId,
    dropdown,
    dataAttrSuffix = '',
}: {
    tileId: TileId
    dropdown: DropdownConfig<string>
    dataAttrSuffix?: string
}): JSX.Element {
    const currentLabel = dropdown.options.find((o) => o.value === dropdown.value)?.label ?? dropdown.value
    const items: LemonMenuItem[] = dropdown.options.map((opt) => ({
        label: opt.label ?? String(opt.value),
        active: opt.value === dropdown.value,
        onClick: () => dropdown.onChange(opt.value),
    }))

    return (
        <LemonMenu items={items} placement="bottom-start">
            <button
                type="button"
                className="inline-flex items-center gap-1 m-0 p-0 bg-transparent border-0 cursor-pointer text-base font-semibold text-current hover:text-accent underline decoration-dotted decoration-from-font underline-offset-4 min-w-0 max-w-full"
                data-attr={`web-analytics-title-dropdown-${tileId}${dataAttrSuffix}`}
            >
                <span className="truncate">{currentLabel}</span>
                <IconChevronDown className="text-lg shrink-0" />
            </button>
        </LemonMenu>
    )
}

export function WebTileHeader({
    tileId,
    title,
    titlePrefix,
    titleDropdown,
    breakdownDropdown,
    className,
    docs,
    intervalSelector,
    visualizationToggle,
    openInsight,
    overflowMenuItems,
}: WebTileHeaderProps): JSX.Element {
    const { isWindowLessThan } = useWindowSize()
    const isCompactHeader = isWindowLessThan('lg')
    const isGraph = visualizationToggle?.value === 'graph'
    const titleNode =
        titleDropdown || title || docs || breakdownDropdown ? (
            <h2 className="flex-1 min-w-0 m-0 flex flex-row items-center gap-1.5 text-base font-semibold">
                {titlePrefix && <span className="shrink-0">{titlePrefix}</span>}
                {titleDropdown ? (
                    <TitleDropdown tileId={tileId} dropdown={titleDropdown} />
                ) : (
                    title && <span>{title}</span>
                )}
                {breakdownDropdown && (
                    <>
                        <span className="shrink-0">by</span>
                        <TitleDropdown tileId={tileId} dropdown={breakdownDropdown} dataAttrSuffix="-breakdown" />
                    </>
                )}
                {docs && <LearnMorePopover url={docs.url} title={docs.title} description={docs.description} />}
            </h2>
        ) : (
            <div className="flex-1" />
        )

    return (
        <div
            className={cn(
                'flex flex-row flex-wrap items-center self-stretch gap-1 sm:gap-2 min-h-10 px-3 py-2',
                className
            )}
        >
            {titleNode}

            {intervalSelector && (
                <span className="flex items-center gap-1">
                    <span className="text-secondary text-xs hidden lg:inline">Interval</span>
                    {intervalSelector.node}
                </span>
            )}

            {visualizationToggle && (
                <LemonButton
                    size="small"
                    icon={isGraph ? <IconTableChart /> : <IconLineGraph />}
                    tooltip={isGraph ? 'Show as table' : 'Show as graph'}
                    aria-label={isGraph ? 'Show as table' : 'Show as graph'}
                    onClick={() => visualizationToggle.onChange(isGraph ? 'table' : 'graph')}
                    data-attr={`web-analytics-viz-toggle-${tileId}`}
                />
            )}

            {openInsight && (
                <LemonButton
                    size="small"
                    icon={<IconOpenInNew />}
                    tooltip="Open as new insight"
                    aria-label="Open as new insight"
                    to={openInsight.to}
                    onClick={openInsight.onClick}
                    data-attr={`web-analytics-open-insight-${tileId}`}
                >
                    {isCompactHeader ? undefined : 'Open as insight'}
                </LemonButton>
            )}

            {overflowMenuItems && overflowMenuItems.length > 0 && (
                <LemonMenu items={overflowMenuItems} placement="bottom-end">
                    <LemonButton
                        icon={<IconEllipsis />}
                        size="small"
                        aria-label="More actions"
                        data-attr={`web-analytics-tile-overflow-${tileId}`}
                    />
                </LemonMenu>
            )}
        </div>
    )
}
