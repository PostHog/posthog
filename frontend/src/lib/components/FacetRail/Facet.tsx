import { CSSProperties, useMemo } from 'react'
import { List } from 'react-window'

import { IconChevronDown, IconChevronRight, IconMinusSmall, IconWarning, IconX } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonInput, Link, Tooltip } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'
import { humanFriendlyLargeNumber } from 'lib/utils/numbers'

const ROW_HEIGHT = 33

export interface FacetOption {
    value: string
    label: string
    /** Tailwind bg class for a leading color swatch (e.g. severity colors). */
    color?: string
    /** Number of matching records; rendered right-aligned. Omitted when unavailable. */
    count?: number
}

interface FacetProps {
    title: string
    options: FacetOption[]
    selected: string[]
    /** Values in the excluded state — matching records are filtered out. Disjoint from `selected`. */
    excluded?: string[]
    onToggle: (value: string) => void
    /** Prefix for every data-attr in the facet, e.g. `logs-facet`. These are frozen: autocapture and tests select on them. */
    dataAttrPrefix: string
    zeroCountReason: string
    loading?: boolean
    emptyLabel?: string
    /** When provided, renders a search box above the values (state owned by the caller). */
    searchValue?: string
    onSearchChange?: (value: string) => void
    searchPlaceholder?: string
    collapsed?: boolean
    onToggleCollapsed?: () => void
    /** When set, values render in a fixed-height virtualized list capped at this many pixels. */
    maxHeight?: number
    /** For fixed facets: render zero-count values dimmed, and disabled unless already selected. */
    dimZeroCounts?: boolean
    /** When set, renders a remove control in the header — for user-added custom facets only. */
    onRemove?: () => void
    /** Disables the remove control (with this explanation) while a custom-facet update is in flight. */
    removeDisabledReason?: string
    /** The facet's latest fetch failed — show an error icon and line instead of pretending the list is fresh (suppresses emptyLabel). */
    error?: boolean
    /** Renders a Retry link next to the error message. */
    onRetry?: () => void
}

/**
 * Lowercase a label into a selector-safe slug for data-attrs. Facet values are real resource
 * attributes (pod, deployment, host names) that can carry spaces, quotes, or slashes, so collapse
 * any run of non-alphanumerics to a single hyphen and trim the ends.
 */
function slugify(value: string): string {
    return value
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '-')
        .replace(/^-+|-+$/g, '')
}

/** A single rail facet: a collapsible field title and its selectable values (multi-select = OR), each with a count. */
export function Facet({
    title,
    options,
    selected,
    excluded = [],
    onToggle,
    dataAttrPrefix,
    zeroCountReason,
    loading = false,
    emptyLabel = 'No values',
    searchValue,
    onSearchChange,
    searchPlaceholder = 'Search…',
    collapsed = false,
    onToggleCollapsed,
    maxHeight,
    dimZeroCounts = false,
    error = false,
    onRetry,
    onRemove,
    removeDisabledReason,
}: FacetProps): JSX.Element {
    const dataAttr = `${dataAttrPrefix}-${slugify(title)}`
    const errorMessage = options.length > 0 ? "Couldn't refresh values." : "Couldn't load values."

    const rowProps = useMemo<FacetValueRowProps>(
        () => ({ options, selected, excluded, dataAttr, onToggle, dimZeroCounts, zeroCountReason }),
        [options, selected, excluded, dataAttr, onToggle, dimZeroCounts, zeroCountReason]
    )

    return (
        <div className="mb-3">
            <div className="flex items-center gap-1 w-full px-1 mb-1">
                <button
                    type="button"
                    onClick={onToggleCollapsed}
                    disabled={!onToggleCollapsed}
                    className="flex items-center gap-1 flex-1 min-w-0 text-[10px] font-semibold uppercase tracking-wide text-secondary hover:text-default"
                    data-attr={`${dataAttr}-header`}
                >
                    {collapsed ? <IconChevronRight /> : <IconChevronDown />}
                    <span className="truncate">{title}</span>
                    {error && !loading && (
                        <Tooltip title={collapsed ? `${errorMessage} Expand to retry.` : errorMessage}>
                            <IconWarning className="shrink-0 text-xs text-danger" />
                        </Tooltip>
                    )}
                </button>
                {onRemove && (
                    <LemonButton
                        size="small"
                        icon={<IconX />}
                        onClick={onRemove}
                        disabledReason={removeDisabledReason}
                        tooltip="Remove custom facet"
                        data-attr={`${dataAttr}-remove`}
                    />
                )}
            </div>
            {!collapsed && onSearchChange && (
                <div className="px-1 pb-1">
                    <LemonInput
                        type="search"
                        size="small"
                        fullWidth
                        placeholder={searchPlaceholder}
                        value={searchValue ?? ''}
                        onChange={onSearchChange}
                    />
                </div>
            )}
            {/* A failed fetch shows inline (options may be stale-but-usable below) rather than blanking the facet. */}
            {!collapsed && error && !loading && (
                <div className="px-1 pb-1 text-xs text-secondary" data-attr={`${dataAttr}-error`}>
                    {errorMessage}{' '}
                    {onRetry && (
                        <Link onClick={onRetry} data-attr={`${dataAttr}-retry`}>
                            Retry
                        </Link>
                    )}
                </div>
            )}
            {!collapsed &&
                (loading && options.length === 0 ? (
                    <div className="px-1 text-xs text-muted">Loading…</div>
                ) : options.length === 0 ? (
                    // The error line above already explains the missing values — don't add "No values".
                    !error && <div className="px-1 text-xs text-muted">{emptyLabel}</div>
                ) : (
                    // Dim the list while a refetch is in flight (e.g. typing in search) so there's
                    // feedback that results are updating, rather than the list silently changing.
                    <div className={cn(loading && 'opacity-60 transition-opacity')}>
                        {maxHeight ? (
                            <List<FacetValueRowProps>
                                // eslint-disable-next-line react/forbid-dom-props
                                style={{ width: '100%', height: Math.min(options.length * ROW_HEIGHT, maxHeight) }}
                                rowCount={options.length}
                                rowHeight={ROW_HEIGHT}
                                overscanCount={5}
                                rowComponent={FacetValueRow}
                                rowProps={rowProps}
                            />
                        ) : (
                            <div className="space-y-px">
                                {options.map((option) => (
                                    <FacetValueButton
                                        key={option.value}
                                        option={option}
                                        selected={selected.includes(option.value)}
                                        excluded={excluded.includes(option.value)}
                                        dataAttr={dataAttr}
                                        onToggle={onToggle}
                                        dimZeroCounts={dimZeroCounts}
                                        zeroCountReason={zeroCountReason}
                                    />
                                ))}
                            </div>
                        )}
                    </div>
                ))}
        </div>
    )
}

interface FacetValueRowProps {
    options: FacetOption[]
    selected: string[]
    excluded: string[]
    dataAttr: string
    onToggle: (value: string) => void
    dimZeroCounts: boolean
    zeroCountReason: string
}

function FacetValueRow({
    ariaAttributes,
    index,
    style,
    options,
    selected,
    excluded,
    dataAttr,
    onToggle,
    dimZeroCounts,
    zeroCountReason,
}: {
    ariaAttributes: { 'aria-posinset': number; 'aria-setsize': number; role: 'listitem' }
    index: number
    style: CSSProperties
} & FacetValueRowProps): JSX.Element {
    const option = options[index]
    return (
        // eslint-disable-next-line react/forbid-dom-props
        <div style={style} {...ariaAttributes}>
            <FacetValueButton
                option={option}
                selected={selected.includes(option.value)}
                excluded={excluded.includes(option.value)}
                dataAttr={dataAttr}
                onToggle={onToggle}
                dimZeroCounts={dimZeroCounts}
                zeroCountReason={zeroCountReason}
            />
        </div>
    )
}

function FacetValueButton({
    option,
    selected,
    excluded,
    dataAttr,
    onToggle,
    dimZeroCounts,
    zeroCountReason,
}: {
    option: FacetOption
    selected: boolean
    excluded: boolean
    dataAttr: string
    onToggle: (value: string) => void
    dimZeroCounts: boolean
    zeroCountReason: string
}): JSX.Element {
    // A fixed facet value with no matches in the current scope: dim it, and disable it unless it's
    // already active (selected or excluded), so an active-but-now-empty value can still be cycled off.
    const isActive = selected || excluded
    const isZero = dimZeroCounts && option.count === 0
    // The tri-state is otherwise only visual (checkbox / red minus / line-through), so spell the
    // current state out for screen readers — the button cycles included → excluded → not filtered.
    const stateLabel = excluded ? 'excluded' : selected ? 'included' : 'not filtered'
    return (
        <LemonButton
            type="tertiary"
            size="small"
            fullWidth
            className={cn(isZero && 'opacity-50')}
            disabledReason={isZero && !isActive ? zeroCountReason : undefined}
            aria-label={`${option.label}, ${stateLabel}`}
            icon={
                excluded ? (
                    // Deliberately not LemonCheckbox's `indeterminate` — that means "partially
                    // selected", while this box means "negated".
                    <span
                        aria-hidden
                        className="flex items-center justify-center w-4 h-4 rounded border-[1.5px] border-danger text-danger shrink-0 pointer-events-none"
                    >
                        <IconMinusSmall className="text-sm" />
                    </span>
                ) : (
                    <span aria-hidden className="flex">
                        <LemonCheckbox checked={selected} className="pointer-events-none" />
                    </span>
                )
            }
            onClick={() => onToggle(option.value)}
            data-attr={`${dataAttr}-${slugify(option.value)}`}
        >
            <span className="flex items-center gap-2 min-w-0 w-full">
                {option.color && <span className={cn('w-1 h-3.5 rounded-full shrink-0', option.color)} />}
                {/* Native title so a truncated value is still readable without popover cost per virtualized row. */}
                <span className={cn('truncate flex-1', excluded && 'line-through text-muted')} title={option.label}>
                    {option.label}
                </span>
                {option.count != null && (
                    <span className="shrink-0 text-muted tabular-nums">{humanFriendlyLargeNumber(option.count)}</span>
                )}
            </span>
        </LemonButton>
    )
}
