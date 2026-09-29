import { useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import type { ScoreDefinitionApi } from '../generated/api.schemas'
import { ScoreDefinitionVersionModal } from './ScoreDefinitionVersionModal'

export function ScoreDefinitionVersionButton({
    definition,
    onSuccess,
}: {
    definition: ScoreDefinitionApi
    onSuccess?: (definition: ScoreDefinitionApi) => void
}): JSX.Element {
    const [isOpen, setIsOpen] = useState(false)

    return (
        <>
            <AccessControlAction
                resourceType={AccessControlResourceType.LlmAnalytics}
                minAccessLevel={AccessControlLevel.Editor}
            >
                <LemonButton size="small" onClick={() => setIsOpen(true)}>
                    Create new version
                </LemonButton>
            </AccessControlAction>
            {isOpen && (
                <ScoreDefinitionVersionModal
                    teamId={String(definition.team)}
                    scorerId={definition.id}
                    onClose={() => setIsOpen(false)}
                    onSuccess={onSuccess}
                />
            )}
        </>
    )
}
