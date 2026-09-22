import { useActions, useValues } from 'kea'

import { IconBookmark, IconX } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { SavedViewsModal } from './SavedViewsModal'
import { type TicketViewsLogicProps, ticketViewsLogic } from './ticketViewsLogic'

function SavedViewsButtonInner({ ticketListProps }: TicketViewsLogicProps): JSX.Element {
    const logic = ticketViewsLogic({ ticketListProps })
    const { favoriteViews, viewsLoading, activeView, viewWithUnsavedChanges: editedView } = useValues(logic)
    const { openModal, openSaveModal, loadView, loadViews, saveViewChanges, restoreLoadedView, resetFilters } =
        useActions(logic)
    const editDisabledReason =
        getAccessControlDisabledReason(AccessControlResourceType.Ticket, AccessControlLevel.Editor) ?? undefined
    const shownView = activeView ?? editedView

    return (
        <>
            <LemonMenu
                placement="bottom-start"
                onVisibilityChange={(visible) => visible && loadViews()}
                items={[
                    ...(editedView
                        ? [
                              {
                                  title: `Edited "${editedView.name}"`,
                                  items: [
                                      {
                                          label: 'Save changes',
                                          onClick: saveViewChanges,
                                          disabledReason: editDisabledReason,
                                          'data-attr': 'tickets-save-view-changes',
                                      },
                                      {
                                          label: 'Discard changes',
                                          onClick: restoreLoadedView,
                                      },
                                  ],
                              },
                          ]
                        : []),
                    {
                        title: 'Favorites',
                        items: favoriteViews.length
                            ? favoriteViews.map((view) => ({
                                  label: view.name,
                                  onClick: () => loadView(view),
                              }))
                            : [
                                  {
                                      label: viewsLoading ? 'Loading…' : 'No favorite views yet',
                                      disabledReason: 'Favorite a view to see it here',
                                  },
                              ],
                    },
                    {
                        items: [
                            {
                                label: 'Save current view',
                                onClick: openSaveModal,
                                disabledReason: editDisabledReason,
                                'data-attr': 'tickets-save-current-view',
                            },
                            { label: 'All saved views', onClick: openModal },
                        ],
                    },
                ]}
            >
                <LemonButton
                    size="small"
                    type="secondary"
                    icon={<IconBookmark />}
                    active={!!shownView}
                    tooltip={
                        editedView
                            ? `"${editedView.name}" has filter changes you haven't saved`
                            : activeView
                              ? `Viewing "${activeView.name}"`
                              : undefined
                    }
                    sideAction={
                        shownView
                            ? {
                                  icon: <IconX />,
                                  onClick: resetFilters,
                                  tooltip: 'Clear view and reset filters',
                              }
                            : undefined
                    }
                >
                    {shownView ? (
                        <span className="max-w-50 truncate">
                            {shownView.name}
                            {editedView ? ' (edited)' : ''}
                        </span>
                    ) : (
                        'Saved views'
                    )}
                </LemonButton>
            </LemonMenu>
            <SavedViewsModal ticketListProps={ticketListProps} />
        </>
    )
}

export function SavedViewsButton({ ticketListProps }: TicketViewsLogicProps): JSX.Element | null {
    return <SavedViewsButtonInner ticketListProps={ticketListProps} />
}
