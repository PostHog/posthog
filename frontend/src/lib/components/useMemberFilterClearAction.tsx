import { RefObject, useEffect, useRef } from 'react'

import { IconX } from '@posthog/icons'

import { SideAction } from 'lib/lemon-ui/LemonButton'

export function useMemberFilterClearAction(
    hasSelection: boolean,
    onClear: () => void
): { triggerRef: RefObject<HTMLButtonElement>; sideAction: SideAction | null } {
    const triggerRef = useRef<HTMLButtonElement>(null)
    const focusTriggerAfterClear = useRef(false)

    // The × unmounts when the selection becomes empty, so the focus falls to the page body.
    // Move the focus to the trigger so that keyboard and screen reader users keep their place.
    useEffect(() => {
        if (!hasSelection && focusTriggerAfterClear.current) {
            focusTriggerAfterClear.current = false
            triggerRef.current?.focus()
        }
    }, [hasSelection])

    return {
        triggerRef,
        sideAction: hasSelection
            ? {
                  icon: <IconX />,
                  tooltip: 'Clear selection',
                  divider: false,
                  'data-attr': 'member-filter-clear-x',
                  onClick: (e) => {
                      e.stopPropagation()
                      focusTriggerAfterClear.current = true
                      onClear()
                  },
              }
            : null,
    }
}
