import { useActions, useValues } from 'kea'

import { IconBookmark, IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { supportTicketsSceneLogic } from '../../scenes/tickets/supportTicketsSceneLogic'
import { SavedViewsModal } from './SavedViewsModal'
import { type TicketViewsLogicProps, ticketViewsLogic } from './ticketViewsLogic'

function SavedViewsButtonInner({ id }: TicketViewsLogicProps): JSX.Element {
    const { openModal } = useActions(ticketViewsLogic({ id }))
    const { activeView } = useValues(supportTicketsSceneLogic)
    const { clearActiveView } = useActions(supportTicketsSceneLogic)

    return (
        <>
            <LemonButton
                size="small"
                type="secondary"
                icon={<IconBookmark />}
                onClick={openModal}
                active={!!activeView}
                tooltip={activeView ? `Viewing "${activeView.name}"` : undefined}
                sideAction={
                    activeView
                        ? {
                              icon: <IconX />,
                              onClick: clearActiveView,
                              tooltip: 'Clear view (keeps current filters)',
                          }
                        : undefined
                }
            >
                {activeView ? <span className="max-w-50 truncate">{activeView.name}</span> : 'Saved views'}
            </LemonButton>
            <SavedViewsModal id={id} />
        </>
    )
}

export function SavedViewsButton({ id }: TicketViewsLogicProps): JSX.Element | null {
    return <SavedViewsButtonInner id={id} />
}
