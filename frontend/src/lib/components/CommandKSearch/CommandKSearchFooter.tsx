import { useValues } from 'kea'

import { Kbd, cn } from '@posthog/quill'

import { todayShellLogic } from '~/layout/today/todayShellLogic'

import { commandKSearchLogic } from './commandKSearchLogic'

export function CommandKSearchFooter(): JSX.Element {
    const { highlightIsFilterRow, chips, mode, selectedChipIndex, tabAsksAi } = useValues(commandKSearchLogic)
    const { todayRailEnabled } = useValues(todayShellLogic)

    return (
        <div
            className={cn(
                todayRailEnabled && 'max-md:hidden',
                'flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-border px-2 py-1.5 text-xxs text-muted-foreground select-none'
            )}
        >
            <span className="flex items-center gap-1">
                <Kbd>↑</Kbd>
                <Kbd>↓</Kbd> navigate
            </span>
            <span className="flex items-center gap-1">
                <Kbd>↵</Kbd> open
            </span>
            <span className="flex items-center gap-1">
                <Kbd>⌘↵</Kbd> new tab
            </span>
            {highlightIsFilterRow && (
                <span className="flex items-center gap-1">
                    <Kbd>⇥</Kbd> complete
                </span>
            )}
            {tabAsksAi && (
                <span className="flex items-center gap-1">
                    <Kbd>⇥</Kbd> ask AI
                </span>
            )}
            {chips.length > 0 && (
                <span className="flex items-center gap-1">
                    <Kbd>⌫</Kbd> {selectedChipIndex === null ? 'select filter' : 'remove filter'}
                </span>
            )}
            {selectedChipIndex !== null && (
                <span className="flex items-center gap-1">
                    <Kbd>↵</Kbd> edit filter
                </span>
            )}
            <span className="flex items-center gap-1">
                <Kbd>Esc</Kbd> {mode === 'empty' ? 'close' : 'clear'}
            </span>
        </div>
    )
}
