import { useActions, useValues } from 'kea'

import { IconBookmark, IconX } from '@posthog/icons'

import {
    Button,
    ButtonGroup,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from 'lib/ui/quill'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { supportTicketsSceneLogic } from '../../scenes/tickets/supportTicketsSceneLogic'
import { SavedViewsModal } from './SavedViewsModal'
import { type TicketViewsLogicProps, ticketViewsLogic } from './ticketViewsLogic'

function SavedViewsButtonInner({ id }: TicketViewsLogicProps): JSX.Element {
    const { favoriteViews, viewsLoading } = useValues(ticketViewsLogic({ id }))
    const { openModal, openSaveModal, loadView, loadViews } = useActions(ticketViewsLogic({ id }))
    const { activeView } = useValues(supportTicketsSceneLogic)
    const { resetFilters } = useActions(supportTicketsSceneLogic)
    const editDisabledReason =
        getAccessControlDisabledReason(AccessControlResourceType.Ticket, AccessControlLevel.Editor) ?? undefined

    return (
        <>
            <ButtonGroup>
                <DropdownMenu
                    onOpenChange={(open) => {
                        if (open) {
                            loadViews()
                        }
                    }}
                >
                    <DropdownMenuTrigger
                        render={
                            <Button
                                variant="outline"
                                size="sm"
                                aria-pressed={!!activeView}
                                title={activeView ? `Viewing "${activeView.name}"` : undefined}
                            />
                        }
                    >
                        <IconBookmark />
                        {activeView ? <span className="max-w-50 truncate">{activeView.name}</span> : 'Saved views'}
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="start" className="min-w-48">
                        <DropdownMenuGroup>
                            <DropdownMenuLabel>Favorites</DropdownMenuLabel>
                            {favoriteViews.length ? (
                                favoriteViews.map((view) => (
                                    <DropdownMenuItem key={view.short_id} onClick={() => loadView(view)}>
                                        {view.name}
                                    </DropdownMenuItem>
                                ))
                            ) : (
                                <DropdownMenuItem disabled>
                                    {viewsLoading ? 'Loading…' : 'No favorite views yet'}
                                </DropdownMenuItem>
                            )}
                        </DropdownMenuGroup>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem
                            disabled={!!editDisabledReason}
                            title={editDisabledReason}
                            data-attr="tickets-save-current-view"
                            onClick={openSaveModal}
                        >
                            Save current view
                        </DropdownMenuItem>
                        <DropdownMenuItem onClick={openModal}>All saved views</DropdownMenuItem>
                    </DropdownMenuContent>
                </DropdownMenu>
                {activeView ? (
                    <Tooltip>
                        <TooltipTrigger
                            render={
                                <Button
                                    variant="outline"
                                    size="icon-sm"
                                    onClick={resetFilters}
                                    aria-label="Clear view and reset filters"
                                />
                            }
                        >
                            <IconX />
                        </TooltipTrigger>
                        <TooltipContent>Clear view and reset filters</TooltipContent>
                    </Tooltip>
                ) : null}
            </ButtonGroup>
            <SavedViewsModal id={id} />
        </>
    )
}

export function SavedViewsButton({ id }: TicketViewsLogicProps): JSX.Element | null {
    return <SavedViewsButtonInner id={id} />
}
