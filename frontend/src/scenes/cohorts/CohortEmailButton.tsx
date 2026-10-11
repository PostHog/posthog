import { useActions, useValues } from 'kea'

import { IconLetter, IconWarning } from '@posthog/icons'
import { Spinner } from '@posthog/lemon-ui'

import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'

import {
    cohortAudienceProperties,
    messageAudienceAccessDisabledReason,
} from 'products/workflows/frontend/MessageAudience/messageAudience'
import {
    messageAudienceButtonLabel,
    messageAudienceTooltip,
} from 'products/workflows/frontend/MessageAudience/messageAudienceReadiness'
import { messageAudienceReadinessLogic } from 'products/workflows/frontend/MessageAudience/messageAudienceReadinessLogic'

const LABEL = 'Email this cohort'

/** The scene panel action that opens a broadcast to a saved cohort, labeled with how many people it reaches. */
export function CohortEmailButton({
    cohort,
    disabledReason,
}: {
    cohort: { id: number | 'new' | undefined; name?: string | null }
    disabledReason: string | null
}): JSX.Element {
    const accessDisabledReason = messageAudienceAccessDisabledReason()
    const blockedReason = disabledReason ?? accessDisabledReason
    if (blockedReason || typeof cohort.id !== 'number') {
        return (
            <ButtonPrimitive
                disabledReasons={{ [blockedReason ?? 'Save the cohort first']: true }}
                data-attr="cohort-send-broadcast"
                menuItem
            >
                <IconLetter /> {LABEL}
            </ButtonPrimitive>
        )
    }
    return <CountedCohortEmailButton cohortId={cohort.id} cohortName={cohort.name ?? undefined} />
}

function CountedCohortEmailButton({ cohortId, cohortName }: { cohortId: number; cohortName?: string }): JSX.Element {
    const logic = messageAudienceReadinessLogic({
        audience: {
            properties: cohortAudienceProperties({ id: cohortId, name: cohortName }),
            source: 'cohort',
            sourceRecord: `cohort:${cohortId}`,
            sourceRecordName: cohortName,
        },
    })
    const { readiness, navigating } = useValues(logic)
    const { open } = useActions(logic)

    return (
        <ButtonPrimitive
            onClick={() => open('broadcast')}
            disabledReasons={{
                ...(readiness.disabledReason ? { [readiness.disabledReason]: true } : {}),
                'Checking who already got this email': navigating,
            }}
            data-attr="cohort-send-broadcast"
            tooltip={messageAudienceTooltip(readiness) ?? 'Send a one-time email to everyone in this cohort'}
            menuItem
        >
            <IconLetter /> {messageAudienceButtonLabel(readiness, LABEL)}
            {readiness.countState === 'loading' || navigating ? <Spinner className="ml-auto" /> : null}
            {readiness.warnings.length > 0 ? <IconWarning className="ml-auto text-warning" /> : null}
        </ButtonPrimitive>
    )
}
