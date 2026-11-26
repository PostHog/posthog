import { splitPath } from '~/layout/panel-layout/ProjectTree/utils'
import { FileSystemEntry } from '~/queries/schema/schema-general'

import type { PinTarget } from './sidebarPinsLogic'

// Kept out of `sidebarPinsLogic`, which every logged-in page loads, because only scene pin buttons need it.
export function fileSystemPinTarget(entry: FileSystemEntry | null): PinTarget | null {
    if (!entry?.type || !entry.ref) {
        return null
    }
    return {
        type: entry.type.split('/')[0],
        ref: entry.ref,
        name: splitPath(entry.path).pop() || entry.path,
        href: entry.href,
    }
}
