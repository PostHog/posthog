import { useActions } from 'kea'

import { IconBookmark } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { SavedViewsModal } from './SavedViewsModal'
import { type TicketViewsLogicProps, ticketViewsLogic } from './ticketViewsLogic'

function SavedViewsButtonInner({ id }: TicketViewsLogicProps): JSX.Element {
    const { openModal } = useActions(ticketViewsLogic({ id }))

    return (
        <>
            <LemonButton size="small" type="secondary" icon={<IconBookmark />} onClick={openModal}>
                Saved views
            </LemonButton>
            <SavedViewsModal id={id} />
        </>
    )
}

export function SavedViewsButton({ id }: TicketViewsLogicProps): JSX.Element | null {
    return <SavedViewsButtonInner id={id} />
}
