import { useActions } from 'kea'

import { IconBookmark } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

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
    const enabled = useFeatureFlag('PRODUCT_SUPPORT_TICKET_VIEWS')

    if (!enabled) {
        return null
    }

    return <SavedViewsButtonInner id={id} />
}
