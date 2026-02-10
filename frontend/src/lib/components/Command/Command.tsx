import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useCallback } from 'react'

import { DialogPrimitive, DialogPrimitiveTitle } from 'lib/ui/DialogPrimitive/DialogPrimitive'

import { Search } from '../Search/Search'
import { SearchItem } from '../Search/searchLogic'
import { commandLogic } from './commandLogic'

export function Command(): JSX.Element {
    const { isCommandOpen } = useValues(commandLogic)
    const { closeCommand } = useActions(commandLogic)

    const handleItemSelect = useCallback(
        (item: SearchItem) => {
            closeCommand()
            if (item.href) {
                router.actions.push(item.href)
            }
        },
        [closeCommand]
    )

    const handleAskAiClick = useCallback(() => {
        closeCommand()
    }, [closeCommand])

    return (
        <DialogPrimitive open={isCommandOpen} onOpenChange={(open) => !open && closeCommand()} className="w-[640px]">
            <DialogPrimitiveTitle>Command</DialogPrimitiveTitle>
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
        </DialogPrimitive>
    )
}
