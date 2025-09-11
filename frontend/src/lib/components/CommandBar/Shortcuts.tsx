import { useMountedLogic } from 'kea'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'

import { shortcutsLogic } from './shortcutsLogic'

export const Shortcuts = (): JSX.Element => {
    useMountedLogic(shortcutsLogic)

    return (
        <div className="flex flex-col h-full p-5">
            <h3>Keyboard shortcuts</h3>
            <h4>Site-wide shortcuts</h4>
            <div className="deprecated-space-y-1">
                <div>
                    <KeyboardShortcut command k /> Open search
                </div>
                <div>
                    <KeyboardShortcut command shift k /> Open command palette
                </div>
            </div>
        </div>
    )
}
