import { IconFilter } from '@posthog/icons'
import { LemonCheckbox, LemonMenuItems, LemonMenuOverlay, LemonTableColumn } from '@posthog/lemon-ui'

export interface ColumnValueFilterOption<V> {
    value: V
    label: string
}

export interface ColumnValueFilterProps<V> {
    /** Section heading inside the menu, e.g. "Show only". */
    title?: string
    /** The full set of values the column can take, in the order to list them. */
    options: ColumnValueFilterOption<V>[]
    /** Currently selected values. Empty means "no filter". */
    selected: V[]
    onChange: (selected: V[]) => void
    'data-attr'?: string
}

function ColumnValueFilterOverlay<V>({
    title = 'Show only',
    options,
    selected,
    onChange,
    'data-attr': dataAttr,
}: ColumnValueFilterProps<V>): JSX.Element {
    const items: LemonMenuItems = [
        {
            title,
            items: options.map((option) => ({
                icon: <LemonCheckbox checked={selected.includes(option.value)} className="pointer-events-none" />,
                label: option.label,
                'data-attr': dataAttr,
                onClick: () =>
                    onChange(
                        selected.includes(option.value)
                            ? selected.filter((value) => value !== option.value)
                            : options
                                  .map(({ value }) => value)
                                  .filter((value) => selected.includes(value) || value === option.value)
                    ),
            })),
        },
    ]
    return <LemonMenuOverlay items={items} />
}

/**
 * Header-menu filter for a categorical LemonTable column: a filter icon in the column title that opens
 * a checkbox list of the column's possible values, with a badge showing how many are selected.
 *
 * Spread the result into the column definition. Filtering itself stays with the caller (server-side
 * or client-side), this only owns the header UI, so any table with an enumerated column can reuse it.
 */
export function columnValueFilter<T extends Record<string, any>, V>(
    props: ColumnValueFilterProps<V>
): Pick<LemonTableColumn<T, keyof T | undefined>, 'more' | 'moreIcon' | 'moreFilterCount'> {
    return {
        more: <ColumnValueFilterOverlay {...props} />,
        moreIcon: <IconFilter />,
        moreFilterCount: props.selected.length,
    }
}
