import { router } from 'kea-router'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { urls } from 'scenes/urls'

import { CohortType } from '~/types'

import {
    captureMessageAudienceClicked,
    cohortAudienceProperties,
    messageAudienceUrl,
} from 'products/workflows/frontend/MessageAudience/messageAudience'

/** Confirms a static cohort saved from a list of people, with links to the cohort and to a broadcast for it. */
export function cohortSavedToast(cohort: Pick<CohortType, 'id' | 'name'>, source: string, toastId?: string): void {
    const savedCohort = { id: cohort.id as number, name: cohort.name }
    lemonToast.success('Cohort saved', {
        toastId,
        button: {
            label: 'View cohort',
            action: () => router.actions.push(urls.cohort(savedCohort.id)),
        },
        secondaryButton: {
            label: 'Send a broadcast',
            dataAttr: `message-audience-${source}-broadcast`,
            action: () => {
                captureMessageAudienceClicked(source, 'broadcast')
                router.actions.push(
                    messageAudienceUrl({ properties: cohortAudienceProperties(savedCohort), source }, 'broadcast')
                )
            },
        },
    })
}
