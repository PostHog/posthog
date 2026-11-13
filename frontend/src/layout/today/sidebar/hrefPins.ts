import { splitPath } from '~/layout/panel-layout/ProjectTree/utils'
import { FileSystemEntry } from '~/queries/schema/schema-general'

import { pinKey } from './sidebarPinsLogic'

/** A pinned record that has no file system row of its own, so it pins by href. */
export interface HrefPin<T extends string> {
    key: string
    type: T
    name: string
    href: string
}

/** The pins of the given types, once each. Keys on the href, so a record starred in the classic navigation shows too. */
export function hrefPinsFromShortcuts<T extends string>(
    shortcuts: FileSystemEntry[],
    types: readonly T[]
): HrefPin<T>[] {
    const isPinType = (type: string | undefined): type is T => (types as readonly (string | undefined)[]).includes(type)
    const pins = new Map<string, HrefPin<T>>()
    for (const shortcut of shortcuts) {
        if (!shortcut.href || !isPinType(shortcut.type)) {
            continue
        }
        const key = pinKey(shortcut.type, shortcut.href)
        if (!pins.has(key)) {
            pins.set(key, {
                key,
                type: shortcut.type,
                name: splitPath(shortcut.path).at(-1) ?? shortcut.path,
                href: shortcut.href,
            })
        }
    }
    return [...pins.values()]
}
