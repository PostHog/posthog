import { useActions, useValues } from 'kea'
import { useId } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import type { ScoreDefinitionApi } from '../generated/api.schemas'
import { ScoreDefinitionVersionModal } from './ScoreDefinitionVersionModal'
import { scoreDefinitionVersionModalLogic } from './scoreDefinitionVersionModalLogic'

export function ScoreDefinitionVersionButton({
    definition,
    onSuccess,
}: {
    definition: ScoreDefinitionApi
    onSuccess?: (definition: ScoreDefinitionApi) => void
}): JSX.Element {
    const instanceKey = useId()
    const logic = scoreDefinitionVersionModalLogic({ instanceKey })
    const { isOpen } = useValues(logic)
    const { openModal, closeModal } = useActions(logic)

    return (
        <>
            <AccessControlAction
                resourceType={AccessControlResourceType.LlmAnalytics}
                minAccessLevel={AccessControlLevel.Editor}
            >
                <LemonButton size="small" onClick={openModal}>
                    Create new version
                </LemonButton>
            </AccessControlAction>
            {isOpen && (
                <ScoreDefinitionVersionModal
                    teamId={String(definition.team)}
                    scorerId={definition.id}
                    onClose={closeModal}
                    onSuccess={onSuccess}
                />
            )}
        </>
    )
}
