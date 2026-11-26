import { useActions, useValues } from 'kea'
import { Fragment } from 'react'

import { IconBookmark, IconChevronDown, IconX } from '@posthog/icons'
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
    cn,
} from '@posthog/quill'

import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { supportTicketsSceneLogic } from '../../scenes/tickets/supportTicketsSceneLogic'
import { savedViewsMenuSections } from './savedViewsMenuSections'
import { SavedViewsModal } from './SavedViewsModal'
import { type TicketViewsLogicProps, ticketViewsLogic } from './ticketViewsLogic'

export function QuillSavedViewsButton({ id }: TicketViewsLogicProps): JSX.Element {
    const { favoriteViews, viewsLoading } = useValues(ticketViewsLogic({ id }))
    const { openModal, openSaveModal, loadView, loadViews } = useActions(ticketViewsLogic({ id }))
    const { activeView } = useValues(supportTicketsSceneLogic)
    const { resetFilters } = useActions(supportTicketsSceneLogic)
    const editDisabledReason =
        getAccessControlDisabledReason(AccessControlResourceType.Ticket, AccessControlLevel.Editor) ?? undefined
    const sections = savedViewsMenuSections({
        favoriteViews,
        viewsLoading,
        editDisabledReason,
        loadView,
        openSaveModal,
        openModal,
    })

    const menu = (
        <DropdownMenu onOpenChange={(open) => open && loadViews()}>
            <DropdownMenuTrigger
                render={
                    <Button
                        variant="outline"
                        tooltip={activeView ? `Viewing "${activeView.name}"` : undefined}
                        className={cn('min-w-0 max-w-60', activeView && 'bg-fill-selected')}
                    />
                }
            >
                <IconBookmark />
                <span className="truncate">{activeView ? activeView.name : 'Saved views'}</span>
                <IconChevronDown />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start">
                {sections.map((section, index) => (
                    <Fragment key={section.title ?? index}>
                        {index > 0 && <DropdownMenuSeparator />}
                        <DropdownMenuGroup>
                            {section.title && <DropdownMenuLabel>{section.title}</DropdownMenuLabel>}
                            {section.items.map((item, itemIndex) => (
                                <DropdownMenuItem
                                    key={`${itemIndex}-${item.label}`}
                                    onClick={item.onClick}
                                    disabledReason={item.disabledReason}
                                    data-attr={item['data-attr']}
                                >
                                    {item.label}
                                </DropdownMenuItem>
                            ))}
                        </DropdownMenuGroup>
                    </Fragment>
                ))}
            </DropdownMenuContent>
        </DropdownMenu>
    )

    return (
        <>
            {activeView ? (
                <ButtonGroup className="min-w-0">
                    {menu}
                    <Button
                        variant="outline"
                        size="icon"
                        aria-label="Clear view and reset filters"
                        tooltip="Clear view and reset filters"
                        onClick={resetFilters}
                    >
                        <IconX />
                    </Button>
                </ButtonGroup>
            ) : (
                menu
            )}
            <SavedViewsModal id={id} />
        </>
    )
}
