import { useActions, useValues } from 'kea'
import { Suspense } from 'react'

import { DialogPrimitive, DialogPrimitiveTitle } from 'lib/ui/DialogPrimitive/DialogPrimitive'
import { cn } from 'lib/utils/css-classes'
import { lazyWithRetry } from 'lib/utils/retryImport'

import { todayShellLogic } from '~/layout/today/todayShellLogic'

import { commandLogic } from './commandLogic'

const CommandKSearch = lazyWithRetry(() =>
    import('../CommandKSearch/CommandKSearch').then(({ CommandKSearch }) => ({ default: CommandKSearch }))
)

const TODAY_PHONE_SHEET =
    'max-md:top-0 max-md:h-dvh max-md:w-screen max-md:max-w-none max-md:max-h-none max-md:supports-[max-height:1dvh]:max-h-none max-md:rounded-none max-md:border-0'

export function Command(): JSX.Element {
    const { isCommandOpen } = useValues(commandLogic)
    const { todayRailEnabled } = useValues(todayShellLogic)
    const { closeCommand } = useActions(commandLogic)

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
