import { useActions, useValues } from 'kea'
import { Suspense, useCallback, useEffect } from 'react'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { DialogPrimitive, DialogPrimitiveTitle } from 'lib/ui/DialogPrimitive/DialogPrimitive'
import { cn } from 'lib/utils/css-classes'
import { navigateToHref } from 'lib/utils/navigateToHref'
import { newInternalTab } from 'lib/utils/newInternalTab'
import { lazyWithRetry } from 'lib/utils/retryImport'

import { todayShellLogic } from '~/layout/today/todayShellLogic'

import { Search } from '../Search/Search'
import { SearchItem } from '../Search/searchItems'
import { commandLogic } from './commandLogic'

// Only flagged users render it, so the palette chunk skips quill for everyone else.
const CommandKSearch = lazyWithRetry(() =>
    import('../CommandKSearch/CommandKSearch').then(({ CommandKSearch }) => ({ default: CommandKSearch }))
)

const TODAY_PHONE_SHEET =
    'max-md:top-0 max-md:h-dvh max-md:w-screen max-md:max-w-none max-md:max-h-none max-md:supports-[max-height:1dvh]:max-h-none max-md:rounded-none max-md:border-0'

export function Command(): JSX.Element {
    const { isCommandOpen, pendingText } = useValues(commandLogic)
    const { todayRailEnabled } = useValues(todayShellLogic)
    const { closeCommand, commandInputReady } = useActions(commandLogic)
    const newCommandKSearch = useFeatureFlag('NEW_COMMAND_K_SEARCH')

    useEffect(() => {
        if (!newCommandKSearch) {
            commandInputReady()
        }
    }, [newCommandKSearch, commandInputReady])

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
                    navigateToHref(item.href)
                }
            }
        },
        [closeCommand]
    )

    const handleAskAiClick = useCallback(() => {
        closeCommand()
    }, [closeCommand])

    if (newCommandKSearch) {
        return (
            <DialogPrimitive
                open={isCommandOpen}
                onOpenChange={(open) => !open && closeCommand()}
                className={cn('w-[640px]', todayRailEnabled && TODAY_PHONE_SHEET)}
            >
                <DialogPrimitiveTitle>Command</DialogPrimitiveTitle>
                {/* Mounted only while open, which scopes the search's caches and requests to one use of the palette. */}
                {isCommandOpen && (
                    <Suspense fallback={null}>
                        <CommandKSearch />
                    </Suspense>
                )}
            </DialogPrimitive>
        )
    }

    return (
        <DialogPrimitive
            open={isCommandOpen}
            onOpenChange={(open) => !open && closeCommand()}
            className={cn('w-[640px]', todayRailEnabled && TODAY_PHONE_SHEET)}
        >
            <DialogPrimitiveTitle>Command</DialogPrimitiveTitle>
            <Search.Root
                logicKey="command"
                isActive={isCommandOpen}
                defaultSearchValue={pendingText}
                onItemSelect={handleItemSelect}
                onAskAiClick={handleAskAiClick}
                showAskAiLink
            >
                {todayRailEnabled ? (
                    <div className="flex items-center">
                        <Search.Input autoFocus className="min-w-0 flex-1" />
                        <ButtonPrimitive
                            className="mr-2 hidden shrink-0 max-md:flex"
                            onClick={closeCommand}
                            data-attr="command-phone-cancel"
                        >
                            Cancel
                        </ButtonPrimitive>
                    </div>
                ) : (
                    <Search.Input autoFocus />
                )}
                <Search.Status />
                <Search.Separator />
                <Search.Results listClassName="pt-0 bg-surface-primary" groupLabelClassName="bg-surface-secondary" />
                {todayRailEnabled ? (
                    <div className="max-md:hidden">
                        <Search.Footer />
                    </div>
                ) : (
                    <Search.Footer />
                )}
            </Search.Root>
        </DialogPrimitive>
    )
}
