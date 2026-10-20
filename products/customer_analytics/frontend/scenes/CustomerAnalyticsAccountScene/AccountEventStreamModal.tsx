import { useActions, useValues } from 'kea'

import { LemonModal } from '@posthog/lemon-ui'

import { AccountEventStreamMembership } from '../../components/EventStream/AccountEventStreamMembership'
import { AccountEventStreamSetupBanner } from '../../components/EventStream/AccountEventStreamSetupBanner'
import { customerAnalyticsAccountSceneLogic } from './customerAnalyticsAccountSceneLogic'

export function AccountEventStreamModal(): JSX.Element {
    const { account, eventStreamModalOpen } = useValues(customerAnalyticsAccountSceneLogic)
    const { closeEventStreamModal } = useActions(customerAnalyticsAccountSceneLogic)

    return (
        <LemonModal isOpen={eventStreamModalOpen} onClose={closeEventStreamModal} title="Event stream" width={480}>
            {eventStreamModalOpen && account && (
                <div className="flex flex-col gap-4">
                    <AccountEventStreamMembership accountId={account.id} externalId={account.external_id ?? ''} />
                    <AccountEventStreamSetupBanner />
                </div>
            )}
        </LemonModal>
    )
}
