import { AccountPropertyOption } from './accountPropertyTypes'

export function selectedAccountPropertyOptions(
    options: AccountPropertyOption[],
    selectedKeys: string[]
): AccountPropertyOption[] {
    const optionsByKey = new Map(options.map((option) => [option.key, option]))
    return selectedKeys.map(
        (key): AccountPropertyOption =>
            optionsByKey.get(key) ?? {
                key,
                label: key,
                kind: key.startsWith('account:')
                    ? 'account'
                    : key.startsWith('field:')
                      ? 'account_field'
                      : key.startsWith('relationship:')
                        ? 'relationship'
                        : 'custom',
            }
    )
}

/** Returns the keys with `activeKey` moved to the position of `overKey`, or null when nothing moves. */
export function reorderedAccountPropertyKeys(
    selectedKeys: string[],
    activeKey: string,
    overKey: string
): string[] | null {
    const from = selectedKeys.indexOf(activeKey)
    const to = selectedKeys.indexOf(overKey)
    if (from < 0 || to < 0 || from === to) {
        return null
    }
    const reordered = [...selectedKeys]
    const [moved] = reordered.splice(from, 1)
    reordered.splice(to, 0, moved)
    return reordered
}

/** Returns the keys with `key` appended, or null when it can't be added. */
export function addedAccountPropertyKeys(
    selectedKeys: string[],
    key: string | undefined,
    blocked: boolean
): string[] | null {
    if (!key || blocked || selectedKeys.includes(key)) {
        return null
    }
    return [...selectedKeys, key]
}
