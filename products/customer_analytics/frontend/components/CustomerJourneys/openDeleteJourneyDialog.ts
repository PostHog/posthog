import { LemonDialog } from '@posthog/lemon-ui'

export function openDeleteJourneyDialog({
    journeyId,
    deleteJourney,
    reportCustomerJourneyDeleted,
}: {
    journeyId: string
    deleteJourney: (journeyId: string) => void
    reportCustomerJourneyDeleted: (journeyId: string) => void
}): void {
    LemonDialog.open({
        title: 'Delete customer journey',
        content: 'Are you sure you want to delete this journey? This action cannot be undone.',
        primaryButton: {
            children: 'Delete',
            onClick: () => {
                reportCustomerJourneyDeleted(journeyId)
                deleteJourney(journeyId)
            },
            status: 'danger',
        },
        secondaryButton: {
            children: 'Cancel',
        },
    })
}
