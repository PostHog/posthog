import { useActions, useValues } from 'kea'

import { KeyboardShortcut } from 'lib/components/KeyboardShortcut/KeyboardShortcut'
import { Search } from 'lib/components/Search/Search'
import { DialogPrimitive, DialogPrimitiveTitle } from 'lib/ui/DialogPrimitive/DialogPrimitive'

import { osSpotlightLogic } from './osSpotlightLogic'

/** The app's command menu, with results that open in OS windows. Replaces `Command` on the OS page. */
export function OsSpotlight(): JSX.Element {
    const { isSpotlightOpen } = useValues(osSpotlightLogic)
    const { closeSpotlight, selectResult } = useActions(osSpotlightLogic)

    return (
        <DialogPrimitive
            open={isSpotlightOpen}
            onOpenChange={(open) => !open && closeSpotlight()}
            className="w-[640px]"
        >
            <DialogPrimitiveTitle>Spotlight</DialogPrimitiveTitle>
            <Search.Root
                logicKey="command"
                isActive={isSpotlightOpen}
                onItemSelect={(item, newWindow) => selectResult(item, !!newWindow)}
                onAskAiClick={closeSpotlight}
                showAskAiLink
            >
                <Search.Input autoFocus />
                <Search.Status />
                <Search.Separator />
                <Search.Results listClassName="pt-0 bg-surface-primary" groupLabelClassName="bg-surface-secondary" />
                {/* The default footer promises a browser tab, but here Cmd+Enter opens a window. */}
                <Search.Footer>
                    <span>
                        <KeyboardShortcut arrowup arrowdown preserveOrder /> to navigate
                    </span>
                    <span>
                        <KeyboardShortcut enter /> to open
                    </span>
                    <span>
                        <KeyboardShortcut command enter /> to open in a new window
                    </span>
                    <span>
                        <KeyboardShortcut escape /> to close
                    </span>
                </Search.Footer>
            </Search.Root>
        </DialogPrimitive>
    )
}
