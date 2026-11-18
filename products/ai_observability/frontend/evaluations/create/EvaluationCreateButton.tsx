import { useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { llmEvaluationLogic } from '../llmEvaluationLogic'

/** The create action, named for whether the evaluation starts running, and held back for people without edit access. */
export function EvaluationCreateButton({
    onCreate,
    disabledReason,
    fullWidth = false,
    'data-attr': dataAttr,
}: {
    onCreate: () => void
    disabledReason?: string
    fullWidth?: boolean
    'data-attr': string
}): JSX.Element | null {
    const { evaluation, evaluationFormSubmitting } = useValues(llmEvaluationLogic)

    if (!evaluation) {
        return null
    }
    return (
        <AccessControlAction
            resourceType={AccessControlResourceType.Evaluation}
            minAccessLevel={AccessControlLevel.Editor}
            userAccessLevel={evaluation.user_access_level ?? undefined}
        >
            <LemonButton
                type="primary"
                center={fullWidth}
                fullWidth={fullWidth}
                onClick={onCreate}
                loading={evaluationFormSubmitting}
                disabledReason={disabledReason}
                data-attr={dataAttr}
            >
                {evaluation.enabled ? 'Create and start' : 'Create paused'}
            </LemonButton>
        </AccessControlAction>
    )
}
