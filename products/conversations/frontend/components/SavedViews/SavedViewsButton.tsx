import { useActions, useValues } from 'kea'

import { IconBookmark } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from 'lib/ui/quill'

import { supportTicketsSceneLogic } from '../../scenes/tickets/supportTicketsSceneLogic'
import { SavedViewsModal } from './SavedViewsModal'
import { type TicketViewsLogicProps, ticketViewsLogic } from './ticketViewsLogic'

function SavedViewsButtonInner({ id }: TicketViewsLogicProps): JSX.Element {
    const { favoriteViews, viewsLoading } = useValues(ticketViewsLogic({ id }))
    const { openModal, loadView, loadViews } = useActions(ticketViewsLogic({ id }))
    const { activeView } = useValues(supportTicketsSceneLogic)
    const { resetFilters } = useActions(supportTicketsSceneLogic)

    return (
        <>
            <DropdownMenu onOpenChange={(open) => open && loadViews()}>
                <DropdownMenuTrigger
                    render={
                        <LemonButton
                            size="small"
                            type="secondary"
                            icon={<IconBookmark />}
                            active={!!activeView}
                            tooltip={activeView ? `Viewing "${activeView.name}"` : undefined}
                        >
                            {activeView ? <span className="max-w-50 truncate">{activeView.name}</span> : 'Saved views'}
                        </LemonButton>
                    }
                />
                <DropdownMenuContent align="start" className="min-w-[220px]">
                    <DropdownMenuGroup>
                        <DropdownMenuLabel>Favorites</DropdownMenuLabel>
                        {favoriteViews.length ? (
                            favoriteViews.map((view) => (
                                <DropdownMenuItem key={view.short_id} onClick={() => loadView(view)}>
                                    <span className="truncate">{view.name}</span>
                                </DropdownMenuItem>
                            ))
                        ) : (
                            <DropdownMenuItem disabled>
                                {viewsLoading ? 'Loading…' : 'No favorite views yet'}
                            </DropdownMenuItem>
                        )}
                    </DropdownMenuGroup>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem onClick={openModal}>All saved views</DropdownMenuItem>
                    {activeView && (
                        <>
                            <DropdownMenuSeparator />
                            <DropdownMenuItem onClick={resetFilters}>Clear view and reset filters</DropdownMenuItem>
                        </>
                    )}
                </DropdownMenuContent>
            </DropdownMenu>
            <SavedViewsModal id={id} />
        </>
    )
}

export function SavedViewsButton({ id }: TicketViewsLogicProps): JSX.Element | null {
    return <SavedViewsButtonInner id={id} />
}
