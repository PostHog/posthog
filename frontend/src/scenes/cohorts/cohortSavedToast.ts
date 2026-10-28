import { router } from 'kea-router'

import { ToastButton, lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { urls } from 'scenes/urls'

import { CohortType } from '~/types'

import {
    captureMessageAudienceClicked,
    cohortAudienceProperties,
    messageAudienceAccessDisabledReason,
} from 'products/workflows/frontend/MessageAudience/messageAudience'
import { openMessageAudience } from 'products/workflows/frontend/MessageAudience/messageAudienceWarnings'

/** Opens a broadcast for the cohort, or nothing when the user cannot use workflows. */
export function emailCohortToastButton(
    cohort: { id: number; name?: string | null },
    source: string
): ToastButton | undefined {
    if (messageAudienceAccessDisabledReason()) {
        return undefined
    }
    return {
        label: 'Email this cohort',
        dataAttr: `message-audience-${source}-broadcast`,
        action: () => {
            captureMessageAudienceClicked(source, 'broadcast')
            void openMessageAudience(
                {
                    properties: cohortAudienceProperties(cohort),
                    source,
                    draftSource: { source: 'cohort', source_id: String(cohort.id) },
                },
                'broadcast'
            )
        },
    }
}

/** Confirms a static cohort saved from a list of people, with links to the cohort and to a broadcast for it. */
export function cohortSavedToast(cohort: Pick<CohortType, 'id' | 'name'>, source: string, toastId?: string): void {
    const savedCohort = { id: cohort.id as number, name: cohort.name }
    lemonToast.success('Cohort saved', {
        toastId,
        button: {
            label: 'View cohort',
            action: () => router.actions.push(urls.cohort(savedCohort.id)),
        },
        secondaryButton: emailCohortToastButton(savedCohort, source),
    })
}
