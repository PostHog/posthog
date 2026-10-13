import { useCallback, useState } from 'react'

import { IconCopy } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Popover } from 'lib/lemon-ui/Popover/Popover'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

interface CellCopyMenuState {
    element: HTMLElement
    text: string
}

/** Shared state + popover for a right-click "Copy cell contents" affordance. Callers own the
 *  cell-specific logic (extracting the copyable text, deciding when to fall back to the native
 *  context menu) and call `openCopyMenu`/`closeCopyMenu`; this hook only owns the popover itself. */
export function useCellCopyContextMenu(): {
    closeCopyMenu: () => void
    openCopyMenu: (element: HTMLElement, text: string) => void
    copyMenu: JSX.Element
} {
    const [menu, setMenu] = useState<CellCopyMenuState | null>(null)

    const closeCopyMenu = useCallback(() => setMenu(null), [])
    const openCopyMenu = useCallback((element: HTMLElement, text: string) => setMenu({ element, text }), [])

    const copyMenu = (
        <Popover
            visible={!!menu}
            referenceElement={menu?.element ?? null}
            onClickOutside={closeCopyMenu}
            placement="bottom-start"
            overlay={
                <LemonButton
                    icon={<IconCopy />}
                    fullWidth
                    size="small"
                    onClick={() => {
                        if (menu) {
                            void copyToClipboard(menu.text, 'cell contents')
                        }
                        closeCopyMenu()
                    }}
                >
                    Copy cell contents
                </LemonButton>
            }
        />
    )

    return { closeCopyMenu, openCopyMenu, copyMenu }
}
