import { useValues } from 'kea'

import { IconClockRewind } from '@posthog/icons'
import { LemonButton, type LemonButtonProps } from '@posthog/lemon-ui'

import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import type { EvaluationResultApi } from '../../generated/api.schemas'
import { evaluationsOverviewLogic } from './evaluationsOverviewLogic'

/** Opens the evaluation's backfills tab. Starting a backfill needs edit access, so the button checks it here. */
export function EvaluationRunOnPastDataButton({
    row,
    onClick,
    size,
    type,
    dataAttr,
}: {
    row: EvaluationResultApi
    onClick: () => void
    size?: LemonButtonProps['size']
    type: LemonButtonProps['type']
    dataAttr: string
}): JSX.Element {
    const { configById, evaluationUrl } = useValues(evaluationsOverviewLogic)
    return (
        <LemonButton
            size={size}
            type={type}
            icon={<IconClockRewind />}
            to={evaluationUrl(row.id, { evaluation_tab: 'backfills' })}
            onClick={onClick}
            disabledReason={getAccessControlDisabledReason(
                AccessControlResourceType.Evaluation,
                AccessControlLevel.Editor,
                configById.get(row.id)?.user_access_level ?? undefined
            )}
            data-attr={dataAttr}
        >
            Run on past data
        </LemonButton>
    )
}
