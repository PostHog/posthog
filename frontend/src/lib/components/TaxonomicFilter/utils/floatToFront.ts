/** Move the element at `index` to the front, preserving the order of the rest.
 *  No-op when `index <= 0` (already first, or not found via `findIndex` -> -1).
 *  Shared by the rebuild menu's `Combobox` and the legacy `infiniteListLogic`
 *  so the committed-selection promotion behaves identically across surfaces. */
export function floatToFront<T>(list: T[], index: number): T[] {
    if (index <= 0) {
        return list
    }
    return [list[index], ...list.slice(0, index), ...list.slice(index + 1)]
}
