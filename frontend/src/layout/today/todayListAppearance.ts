/** The details a sidebar session row can show under its title, in PostHog Desktop's order. */
export const TODAY_LIST_ITEM_FIELDS = ['space', 'repository', 'branch', 'creator', 'activity'] as const

export type TodayListItemField = (typeof TODAY_LIST_ITEM_FIELDS)[number]

export const TODAY_LIST_ITEM_FIELD_LABELS: Record<TodayListItemField, string> = {
    space: 'Space',
    repository: 'Repository',
    branch: 'Branch',
    creator: 'Creator',
    activity: 'Last activity',
}

/** One detail on a row's second line. `title` holds what the short text leaves out, like the exact time behind "2h ago". */
export interface TodayListItemDetail {
    field: TodayListItemField
    text: string
    title?: string
}

export type TodayListItemValues = Partial<
    Record<TodayListItemField, Omit<TodayListItemDetail, 'field'> | string | null | undefined>
>

/** The chosen details that have a value, in the chosen order. An empty list keeps the row on one line. */
export function listItemDetails(
    values: TodayListItemValues,
    fields: readonly TodayListItemField[]
): TodayListItemDetail[] {
    const details: TodayListItemDetail[] = []
    for (const field of fields) {
        const value = values[field]
        const detail = typeof value === 'string' ? { text: value, title: undefined } : value
        if (detail?.text.trim()) {
            details.push({ field, text: detail.text.trim(), title: detail.title })
        }
    }
    return details
}

/** The chosen fields first, in their order, then the rest, so the dialog lists every field once. */
export function orderedListItemFields(selected: readonly TodayListItemField[]): TodayListItemField[] {
    return [...selected, ...TODAY_LIST_ITEM_FIELDS.filter((field) => !selected.includes(field))]
}

export function moveListItemField(
    fields: readonly TodayListItemField[],
    field: TodayListItemField,
    offset: -1 | 1
): TodayListItemField[] {
    const from = fields.indexOf(field)
    const to = from + offset
    if (from === -1 || to < 0 || to >= fields.length) {
        return [...fields]
    }
    const next = [...fields]
    next.splice(from, 1)
    next.splice(to, 0, field)
    return next
}
