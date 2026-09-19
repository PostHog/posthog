import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

/** An export menu item. A format with a handler of its own is drawn in the browser. */
export interface ExportAccessItem {
    onClick?: () => void
}

export interface ExportAccessReasons {
    /** Reason the menu as a whole cannot be opened, or null when it holds a format drawn in the browser. */
    menu: string | null
    /** Reason one format cannot be produced, or null when that format is drawn in the browser. */
    forItem: (item: ExportAccessItem) => string | null
}

/**
 * Creating an export requires editor access to the export resource. It is applied per format rather
 * than to the whole menu, because a format produced in the browser creates no export asset: it
 * rasterizes what the person is already looking at, which they can screenshot anyway.
 */
export function getExportAccessReasons(items: ExportAccessItem[]): ExportAccessReasons {
    const reason = getAccessControlDisabledReason(AccessControlResourceType.Export, AccessControlLevel.Editor)
    return {
        menu: items.some((item) => item.onClick) ? null : reason,
        forItem: (item) => (item.onClick ? null : reason),
    }
}
