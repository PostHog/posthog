import posthog from 'posthog-js'
import { useState } from 'react'

import { IconKeyboard } from '@posthog/icons'
import { LemonButton, Popover } from '@posthog/lemon-ui'

import { DashboardShortcutsList, useDashboardShortcuts } from './DashboardShortcutsList'

export function DashboardShortcuts(): JSX.Element {
    const [isOpen, setIsOpen] = useState(false)
    const shortcuts = useDashboardShortcuts()

    return (
        <Popover
            visible={isOpen}
            onClickOutside={() => setIsOpen(false)}
            placement="bottom-end"
            overlay={
                <div className="p-2 w-80 max-w-[calc(100vw-2rem)]">
                    <DashboardShortcutsList />
                </div>
            }
        >
            <LemonButton
                type="tertiary"
                size="small"
                icon={<IconKeyboard />}
                tooltip="Keyboard shortcuts"
                aria-label="Dashboard keyboard shortcuts"
                aria-expanded={isOpen}
                onClick={() => {
                    if (!isOpen) {
                        posthog.capture('dashboard keyboard shortcuts opened', { shortcut_count: shortcuts.length })
                    }
                    setIsOpen(!isOpen)
                }}
            />
        </Popover>
    )
}
