import { useActions, useValues } from 'kea'

import { LemonButton, LemonDialog } from '@posthog/lemon-ui'

import { customerJourneysLogic } from './customerJourneysLogic'

export function DeleteJourneyButton(): JSX.Element | null {
    const { activeJourney } = useValues(customerJourneysLogic)
    const { deleteJourney } = useActions(customerJourneysLogic)

    if (!activeJourney) {
        return null
    }

    return (
        <LemonButton
            size="small"
            type="secondary"
            status="danger"
            onClick={() =>
                LemonDialog.open({
                    title: 'Delete customer journey',
                    content: 'Are you sure you want to delete this journey? This action cannot be undone.',
                    primaryButton: {
                        children: 'Delete',
                        onClick: () => deleteJourney(activeJourney.id),
                        status: 'danger',
                    },
                    secondaryButton: {
                        children: 'Cancel',
                    },
                })
            }
            tooltip="Delete this journey"
            children="Delete journey"
        />
    )
}
