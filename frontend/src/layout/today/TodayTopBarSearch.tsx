import { useActions } from 'kea'

import { IconSearch } from '@posthog/icons'
import { Button, Kbd } from '@posthog/quill'

import { commandLogic } from 'lib/components/Command/commandLogic'
import { isMac } from 'lib/utils/dom'

export function TodayTopBarSearch(): JSX.Element {
    const { toggleCommand } = useActions(commandLogic)

    return (
        <Button
            variant="outline"
            left
            className="h-7 w-full justify-start gap-2 bg-[var(--today-paper)] px-2 font-normal text-muted-foreground hover:text-foreground"
            onClick={() => toggleCommand('nav-search-bar')}
            data-attr="today-top-bar-search"
        >
            <IconSearch className="size-3.5 shrink-0" />
            <span className="min-w-0 flex-1 truncate text-start">Search this project</span>
            <Kbd className="shrink-0">{isMac() ? '⌘K' : 'Ctrl+K'}</Kbd>
        </Button>
    )
}
