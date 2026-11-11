import { LemonButton } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { pluralize } from 'lib/utils/strings'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import type { EvaluationTarget } from '../types'

export function EvaluationPreviewTestButton({
    count,
    unit,
    loading,
    disabledReason,
    userAccessLevel,
    onTest,
}: {
    count: number
    unit: EvaluationTarget
    loading: boolean
    disabledReason?: string
    userAccessLevel?: AccessControlLevel
    onTest: () => void
}): JSX.Element {
    return (
        // Each run is a call on the team's own provider key, so it takes the edit access that saving takes.
        <AccessControlAction
            resourceType={AccessControlResourceType.Evaluation}
            minAccessLevel={AccessControlLevel.Editor}
            userAccessLevel={userAccessLevel}
        >
            <LemonButton
                type="primary"
                size="small"
                fullWidth
                center
                loading={loading}
                onClick={onTest}
                disabledReason={disabledReason}
                tooltip="Each run is one call on your own API key."
                data-attr="llma-evaluation-create-preview-test"
            >
                {count > 0 ? `Test on ${pluralize(count, unit)}` : 'Test'}
            </LemonButton>
        </AccessControlAction>
    )
}
