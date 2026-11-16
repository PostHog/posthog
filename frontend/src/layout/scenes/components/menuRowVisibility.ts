export type MenuRowKind = 'item' | 'label' | 'separator'

export function visibleMenuRows(kinds: MenuRowKind[]): boolean[] {
    const visible = kinds.map((kind) => kind === 'item')

    let seenItem = false
    let pendingSeparator: number | null = null
    kinds.forEach((kind, index) => {
        if (kind === 'separator') {
            pendingSeparator = index
        } else if (kind === 'item') {
            if (pendingSeparator !== null && seenItem) {
                visible[pendingSeparator] = true
            }
            pendingSeparator = null
            seenItem = true
        }
    })

    const isNextRowCandidate = (index: number): boolean => kinds[index] === 'label' || visible[index]
    kinds.forEach((kind, index) => {
        if (kind !== 'label') {
            return
        }
        const next = kinds.findIndex((_, nextIndex) => nextIndex > index && isNextRowCandidate(nextIndex))
        visible[index] = next !== -1 && kinds[next] === 'item'
    })

    return visible
}
