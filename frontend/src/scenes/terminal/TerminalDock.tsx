import { useActions, useValues } from 'kea'
import { Suspense } from 'react'

import { useShortcut } from 'lib/components/Shortcuts/useShortcut'
import { lazyWithRetry } from 'lib/utils/retryImport'

import { terminalDockLogic } from './terminalDockLogic'

const TerminalPanel = lazyWithRetry(() =>
    import('./TerminalPanel').then(({ TerminalPanel }) => ({ default: TerminalPanel }))
)

export function TerminalDock(): JSX.Element | null {
    const { hasOpened, terminalEnabled } = useValues(terminalDockLogic)
    const { toggleTerminal } = useActions(terminalDockLogic)
    useShortcut({
        name: 'toggle-terminal',
        disabled: !terminalEnabled,
        keybind: [
            ['ctrl', '`'],
            ['ctrl', 'shift', '~'],
            ['command', '`'],
            ['command', 'shift', '~'],
        ],
        intent: 'Toggle terminal',
        interaction: 'function',
        callback: toggleTerminal,
        priority: 10,
    })
    return hasOpened ? (
        <Suspense fallback={null}>
            <TerminalPanel />
        </Suspense>
    ) : null
}
