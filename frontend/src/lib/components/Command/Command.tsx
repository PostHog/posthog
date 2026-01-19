import { Dialog } from '@base-ui/react/dialog'
import { useActions, useValues } from 'kea'
import { useCallback } from 'react'

import { Search } from '../Search/Search'
import { commandLogic } from './commandLogic'

export function Command(): JSX.Element {
    const { isCommandOpen } = useValues(commandLogic)
    const { closeCommand } = useActions(commandLogic)

    const handleItemSelect = useCallback(() => {
        closeCommand()
    }, [closeCommand])

    const handleAskAiClick = useCallback(() => {
        closeCommand()
    }, [closeCommand])

    return (
        <Dialog.Root open={isCommandOpen} onOpenChange={(open) => !open && closeCommand()}>
            <Dialog.Portal>
                <Dialog.Backdrop className="fixed inset-0 min-h-screen min-w-screen bg-black opacity-20 transition-all duration-150 data-[ending-style]:opacity-0 data-[starting-style]:opacity-0 dark:opacity-70 z-[var(--z-modal)]" />
                <Dialog.Popup className="fixed top-1/4 left-1/2 w-[640px] max-w-[calc(100vw-3rem)] max-h-[60vh] -translate-x-1/2 rounded-lg bg-surface-secondary shadow-xl border border-primary transition-all duration-150 data-[ending-style]:scale-95 data-[ending-style]:opacity-0 data-[starting-style]:scale-95 data-[starting-style]:opacity-0 flex flex-col overflow-hidden z-[var(--z-force-modal-above-popovers)]">
                    <Search.Root
                        logicKey="command"
                        isActive={isCommandOpen}
                        onItemSelect={handleItemSelect}
                        onAskAiClick={handleAskAiClick}
                        showAskAiLink
                    >
                        <Search.Input autoFocus />
                        <Search.Status />
                        <Search.Separator />
                        <Search.Results groupLabelClassName="bg-surface-secondary" />
                        <Search.Footer />
                    </Search.Root>
                </Dialog.Popup>
            </Dialog.Portal>
        </Dialog.Root>
    )
}
