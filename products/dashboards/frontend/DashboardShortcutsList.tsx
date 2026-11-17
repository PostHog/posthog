import { useValues } from 'kea'

import { RenderKeybind } from 'lib/components/Shortcuts/RenderKeybind'
import { ShortcutType, shortcutLogic } from 'lib/components/Shortcuts/shortcutLogic'
import { Scene } from 'scenes/sceneTypes'

export function useDashboardShortcuts(): ShortcutType[] {
    const { registeredShortcuts, disabledShortcutNames } = useValues(shortcutLogic)
    return registeredShortcuts.filter(
        (shortcut) => shortcut.scope === Scene.Dashboard && !disabledShortcutNames.includes(shortcut.name)
    )
}

export function DashboardShortcutsList(): JSX.Element {
    const shortcuts = useDashboardShortcuts()
    return (
        <>
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
        </>
    )
}
