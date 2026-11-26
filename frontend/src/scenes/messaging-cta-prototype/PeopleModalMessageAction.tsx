// PROTOTYPE, throwaway: variant F, a broadcast in the people modal footer. It saves the people as a static cohort first,
// as "Save as cohort" does, because a broadcast sends to a cohort.
import { useState } from 'react'

import { IconLetter } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import api from 'lib/api'

import { cohortsModel } from '~/models/cohortsModel'
import { CohortType } from '~/types'

import {
    captureMessageAudienceClicked,
    cohortAudienceProperties,
    messageAudienceAccessDisabledReason,
} from 'products/workflows/frontend/MessageAudience/messageAudience'
import { openMessageAudience } from 'products/workflows/frontend/MessageAudience/messageAudienceWarnings'

import { PROTOTYPE_SOURCES, useMessagingCtaVariant } from './messagingCtaPrototype'

export function PeopleModalMessageAction({
    actorsQuery,
    title,
    closeModal,
}: {
    actorsQuery: unknown
    title: string
    closeModal: () => void
}): JSX.Element | null {
    const variant = useMessagingCtaVariant()
    const [saving, setSaving] = useState(false)

    if (variant !== 'F' || !actorsQuery) {
        return null
    }

    return (
        <LemonButton
            type="secondary"
            icon={<IconLetter />}
            loading={saving}
            onClick={async () => {
                captureMessageAudienceClicked(PROTOTYPE_SOURCES.peopleModal, 'broadcast')
                setSaving(true)
                try {
                    // nosemgrep: prefer-codegen-api -- PROTOTYPE: mirrors personsModalLogic.saveAsCohort.
                    const cohort: CohortType = await api.create('api/cohort', {
                        is_static: true,
                        name: title,
                        query: actorsQuery,
                    })
                    cohortsModel.actions.cohortCreated(cohort)
                    closeModal()
                    const saved = { id: cohort.id as number, name: cohort.name }
                    await openMessageAudience(
                        {
                            properties: cohortAudienceProperties(saved),
                            source: PROTOTYPE_SOURCES.peopleModal,
                            sourceRecord: `cohort:${saved.id}`,
                            draftSource: { source: 'cohort', source_id: String(saved.id) },
                        },
                        'broadcast'
                    )
                } finally {
                    setSaving(false)
                }
            }}
            disabledReason={messageAudienceAccessDisabledReason()}
            tooltip="Saves these people as a cohort and opens a broadcast to them. Send yourself a test before it goes out."
            data-attr="person-modal-message"
        >
            Email these people
        </LemonButton>
    )
}
