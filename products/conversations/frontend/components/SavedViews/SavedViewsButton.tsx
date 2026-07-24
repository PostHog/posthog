import { useActions, useValues } from 'kea'

import { IconBookmark, IconX } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

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
            <LemonMenu
                placement="bottom-start"
                onVisibilityChange={(visible) => visible && loadViews()}
                items={[
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
                                  tooltip: 'Clear view and reset filters',
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
