/** Move the element at `index` to `offset` (0 by default, or 1 to preserve a leading
 *  catch-all row), preserving the order of everything else.
 *  No-op when `index <= offset` (already in place, or not found via `findIndex` -> -1).
 *  Shared by the rebuild menu's `Combobox` and the legacy `infiniteListLogic`
 *  for the committed-selection promotion; callers choose the offset per surface. */
export function floatToFront<T>(list: T[], index: number, offset = 0): T[] {
    if (index <= offset) {
        return list
    }
    return [...list.slice(0, offset), list[index], ...list.slice(offset, index), ...list.slice(index + 1)]
}
