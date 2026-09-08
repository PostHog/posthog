import { useActions, useMountedLogic, useValues } from 'kea'

import { IconBookmark, IconChevronDown } from '@posthog/icons'
import { LemonButton, LemonMenu, LemonSegmentedButton } from '@posthog/lemon-ui'

import { supportTicketsSceneLogic } from '../../scenes/tickets/supportTicketsSceneLogic'
import type { SavedTicketView } from '../../types'
import { SavedViewsModal } from './SavedViewsModal'
import { ticketViewsLogic } from './ticketViewsLogic'

const ALL_TICKETS = '__all__'

export function SavedViewsPicker(): JSX.Element {
    // Follow the ticket list this picker sits above, so an embedded list gets its own views.
    const logic = useMountedLogic(supportTicketsSceneLogic)
    const { favoriteViews } = useValues(ticketViewsLogic(logic.props))
    const { openModal, loadView } = useActions(ticketViewsLogic(logic.props))
    const { activeView } = useValues(logic)
    const { resetFilters } = useActions(logic)

    // A view loaded from the modal or a URL may not be a favorite, but it still needs a
    // selected segment so the picker never shows "All tickets" while a view is applied.
    const pickerViews: SavedTicketView[] =
        activeView && !favoriteViews.some((view) => view.short_id === activeView.short_id)
            ? [activeView, ...favoriteViews]
            : favoriteViews
    const selected = activeView?.short_id ?? ALL_TICKETS

    const selectView = (shortId: string): void => {
        if (shortId === ALL_TICKETS) {
            resetFilters()
            return
        }
        const view = pickerViews.find((candidate) => candidate.short_id === shortId)
        if (view) {
            loadView(view)
        }
    }

    if (pickerViews.length === 0) {
        return (
            <>
                <LemonButton
                    size="small"
                    type="secondary"
                    icon={<IconBookmark />}
                    onClick={openModal}
                    data-attr="support-saved-views"
                >
                    Saved views
                </LemonButton>
                <SavedViewsModal />
            </>
        )
    }

    return (
        <div className="flex items-center gap-1 min-w-0">
            {/* The segmented control needs room for every favorite, so a narrow scene gets a
                single dropdown with the same choices instead. */}
            <div className="hidden @xl/main-content:block min-w-0">
                <LemonSegmentedButton
                    size="small"
                    value={selected}
                    onChange={selectView}
                    options={[
                        { value: ALL_TICKETS, label: 'All tickets' },
                        ...pickerViews.map((view) => ({
                            value: view.short_id,
                            label: <span className="max-w-40 truncate">{view.name}</span>,
                            tooltip: view.name,
                        })),
                    ]}
                />
            </div>
            <div className="@xl/main-content:hidden min-w-0">
                <LemonMenu
                    items={[
                        {
                            label: 'All tickets',
                            active: selected === ALL_TICKETS,
                            onClick: () => selectView(ALL_TICKETS),
                        },
                        ...pickerViews.map((view) => ({
                            label: view.name,
                            active: selected === view.short_id,
                            onClick: () => selectView(view.short_id),
                        })),
                    ]}
                >
                    <LemonButton size="small" type="secondary" sideIcon={<IconChevronDown />}>
                        <span className="max-w-50 truncate">{activeView?.name ?? 'All tickets'}</span>
                    </LemonButton>
                </LemonMenu>
            </div>
            <LemonButton
                size="small"
                type="tertiary"
                icon={<IconBookmark />}
                tooltip="Saved views"
                aria-label="Saved views"
                onClick={openModal}
                data-attr="support-saved-views"
            />
            <SavedViewsModal />
        </div>
    )
}
