import { PageHeader } from 'lib/components/PageHeader'
import React from 'react'
import { EventsTab, EventsTabs } from '.'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { useValues } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'

export function EventPageHeader({ activeTab, hideTabs }: { activeTab: EventsTab; hideTabs?: boolean }): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)

    return featureFlags[FEATURE_FLAGS.COLLABORATIONS_TAXONOMY] ? (
        <>
            <PageHeader
                title="Events"
                caption="See events being sent to this project. Event history is limited to the last twelve months."
            />
        </>
    ) : (
        <>
            <PageHeader
                title="Events & Actions"
                caption="See events being sent to this project and manage custom actions. Event history is limited to the last twelve months."
                tabbedPage
            />
            {!hideTabs && <EventsTabs tab={activeTab} />}
        </>
    )
}
