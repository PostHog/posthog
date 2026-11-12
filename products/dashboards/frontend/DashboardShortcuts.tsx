import { useValues } from 'kea'
import posthog from 'posthog-js'
import { useState } from 'react'

import { IconKeyboard } from '@posthog/icons'
import { LemonButton, Popover } from '@posthog/lemon-ui'

import { RenderKeybind } from 'lib/components/Shortcuts/RenderKeybind'
import { shortcutLogic } from 'lib/components/Shortcuts/shortcutLogic'
import { Scene } from 'scenes/sceneTypes'

export function DashboardShortcuts(): JSX.Element {
    const [isOpen, setIsOpen] = useState(false)
    const { registeredShortcuts, disabledShortcutNames } = useValues(shortcutLogic)
    const shortcuts = registeredShortcuts.filter(
        (shortcut) => shortcut.scope === Scene.Dashboard && !disabledShortcutNames.includes(shortcut.name)
    )

    return (
        <Popover
            visible={isOpen}
            onClickOutside={() => setIsOpen(false)}
            placement="bottom-end"
            overlay={
                <div className="p-2 w-80 max-w-[calc(100vw-2rem)]">
                    <h4 className="mb-3">Dashboard keyboard shortcuts</h4>
                    {shortcuts.length ? (
                        <dl className="m-0 space-y-3">
                            {shortcuts.map((shortcut) => (
                                <div key={shortcut.name} className="flex items-center justify-between gap-4">
                                    <dt>{shortcut.intent}</dt>
                                    <dd className="m-0 shrink-0">
                                        <RenderKeybind keybind={shortcut.keybind} />
                                    </dd>
                                </div>
                            ))}
                        </dl>
                    ) : (
                        <p className="m-0 text-muted">No dashboard shortcuts are currently available.</p>
                    )}
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
