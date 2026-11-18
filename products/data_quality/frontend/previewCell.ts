/**
 * Render a raw HogQL result value as plain text for the preview table.
 *
 * LemonTable treats any non-null, non-element object cell as a cell representation and spreads its
 * `props` onto the `<td>`, so a value shaped like `{ props: { dangerouslySetInnerHTML } }` would
 * inject markup. Stringifying objects and arrays keeps every cell a primitive, which also stops
 * array/object columns from rendering as blank cells.
 */
export function formatPreviewCell(value: unknown): string {
    if (value === null || value === undefined) {
        return ''
    }
    if (typeof value === 'object') {
        return JSON.stringify(value)
    }
    return String(value)
}
