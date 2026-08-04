import { useActions, useValues } from 'kea'

import { IconBookmark, IconPin, IconPinFilled, IconX } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { supportTicketsSceneLogic } from '../../scenes/tickets/supportTicketsSceneLogic'
import { SavedViewsModal } from './SavedViewsModal'
import { type TicketViewsLogicProps, ticketViewsLogic } from './ticketViewsLogic'

function SavedViewsButtonInner({ id }: TicketViewsLogicProps): JSX.Element {
    const { dropdownViews, viewsLoading } = useValues(ticketViewsLogic({ id }))
    const { openModal, loadView, loadViews, setViewAsDefault, clearDefaultView } = useActions(ticketViewsLogic({ id }))
    const { activeView, defaultView } = useValues(supportTicketsSceneLogic)
    const { resetFilters } = useActions(supportTicketsSceneLogic)
    const activeViewIsDefault = !!activeView && activeView.short_id === defaultView?.short_id

    return (
        <>
            <LemonMenu
                placement="bottom-start"
                onVisibilityChange={(visible) => visible && loadViews()}
                items={[
                    {
                        // Not just favorites: the default heads this list even when it isn't one
                        title: 'Your views',
                        items: dropdownViews.length
                            ? dropdownViews.map((view) => ({
                                  label: view.name,
                                  icon: view.is_default ? <IconPinFilled className="text-accent" /> : undefined,
                                  tooltip: view.is_default ? 'Your default view' : undefined,
                                  onClick: () => loadView(view),
                                  sideAction: {
                                      icon: view.is_default ? <IconPinFilled /> : <IconPin />,
                                      tooltip: view.is_default ? 'Remove my default' : 'Set as my default',
                                      onClick: () =>
                                          view.is_default ? clearDefaultView(view) : setViewAsDefault(view),
                                  },
                              }))
                            : [
                                  {
                                      label: viewsLoading ? 'Loading…' : 'No favorites or default yet',
                                      disabledReason: 'Favorite a view or set your default to see it here',
                                  },
                              ],
                    },
                    {
                        items: [{ label: 'All saved views', onClick: openModal }],
                    },
                ]}
            >
                <LemonButton
                    size="small"
                    type="secondary"
                    icon={<IconBookmark />}
                    active={!!activeView}
                    tooltip={activeView ? `Viewing "${activeView.name}"` : undefined}
                    sideAction={
                        activeView
                            ? {
                                  icon: <IconX />,
                                  onClick: resetFilters,
                                  tooltip: activeViewIsDefault
                                      ? 'Clear view and reset filters. Your default stays set.'
                                      : 'Clear view and reset filters',
                              }
                            : undefined
                    }
                >
                    {activeView ? <span className="max-w-50 truncate">{activeView.name}</span> : 'Saved views'}
                </LemonButton>
            </LemonMenu>
            <SavedViewsModal id={id} />
        </>
    )
}

export function SavedViewsButton({ id }: TicketViewsLogicProps): JSX.Element | null {
    return <SavedViewsButtonInner id={id} />
}
