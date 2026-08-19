import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useCallback } from 'react'

import { DialogPrimitive, DialogPrimitiveTitle } from 'lib/ui/DialogPrimitive/DialogPrimitive'
import { newInternalTab } from 'lib/utils/newInternalTab'

import { Search } from '../Search/Search'
import { SearchItem } from '../Search/searchLogic'
import { commandLogic, toCommandHistoryItem } from './commandLogic'

export function Command(): JSX.Element {
    const { currentTeamId, isCommandOpen, recentlySelectedItems } = useValues(commandLogic)
    const { closeCommand, recordCommandSelection } = useActions(commandLogic)

    const handleItemSelect = useCallback(
        (item: SearchItem, openInNewTab?: boolean) => {
            closeCommand()
            if (item.onSelect) {
                item.onSelect()
                return
            }
            if (item.href) {
                if (openInNewTab) {
                    newInternalTab(item.href)
                } else {
                    router.actions.push(item.href)
                }
            }
        },
        [closeCommand]
    )

    const handleItemClick = useCallback(
        (item: SearchItem) => {
            recordCommandSelection(toCommandHistoryItem(item, currentTeamId))
        },
        [currentTeamId, recordCommandSelection]
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
                onItemClick={handleItemClick}
                onItemSelect={handleItemSelect}
                onAskAiClick={handleAskAiClick}
                recentlySelectedItems={recentlySelectedItems}
                showAskAiLink
            >
                <Search.Input autoFocus />
                <Search.Status />
                <Search.Separator />
                <Search.Results listClassName="pt-0 bg-surface-primary" groupLabelClassName="bg-surface-secondary" />
                <Search.Footer />
            </Search.Root>
        </DialogPrimitive>
    )
}
