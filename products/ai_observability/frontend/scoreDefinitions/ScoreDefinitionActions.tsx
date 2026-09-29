import { useState } from 'react'

import { IconEllipsis } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import type { ScoreDefinitionApi } from '../generated/api.schemas'
import type { ScoreDefinitionModalMode } from './scoreDefinitionModalUtils'
import { ScoreDefinitionVersionModal } from './ScoreDefinitionVersionModal'

export function ScoreDefinitionActions({
    definition,
    archiving,
    openModal,
    toggleArchive,
    onVersionCreated,
}: {
    definition: ScoreDefinitionApi
    archiving: boolean
    openModal: (mode: ScoreDefinitionModalMode, definition: ScoreDefinitionApi) => void
    toggleArchive: (definition: ScoreDefinitionApi) => void
    onVersionCreated: () => void
}): JSX.Element {
    const [versionModalOpen, setVersionModalOpen] = useState(false)

    return (
        <>
            <AccessControlAction
                resourceType={AccessControlResourceType.LlmAnalytics}
                minAccessLevel={AccessControlLevel.Editor}
            >
                <LemonMenu
                    items={[
                        {
                            label: 'Edit metadata',
                            onClick: () => openModal('metadata', definition),
                            'data-attr': 'llma-scorer-edit-metadata',
                        },
                        {
                            label: 'Edit config',
                            onClick: () => openModal('config', definition),
                            'data-attr': 'llma-scorer-edit-config',
                        },
                        {
                            label: 'Create new version',
                            onClick: () => setVersionModalOpen(true),
                            'data-attr': 'llma-scorer-new-version',
                        },
                        {
                            label: 'Duplicate',
                            onClick: () => openModal('duplicate', definition),
                            'data-attr': 'llma-scorer-duplicate',
                        },
                        {
                            label: definition.archived ? 'Unarchive' : 'Archive',
                            onClick: () => toggleArchive(definition),
                            disabledReason: archiving ? 'Updating scorer' : undefined,
                            status: definition.archived ? 'default' : 'danger',
                            'data-attr': 'llma-scorer-archive-toggle',
                        },
                    ]}
                >
                    <LemonButton
                        icon={<IconEllipsis />}
                        size="small"
                        aria-label={`Actions for ${definition.name}`}
                        loading={archiving}
                    />
                </LemonMenu>
            </AccessControlAction>
            {versionModalOpen && (
                <ScoreDefinitionVersionModal
                    teamId={String(definition.team)}
                    scorerId={definition.id}
                    onClose={() => setVersionModalOpen(false)}
                    onSuccess={onVersionCreated}
                />
            )}
        </>
    )
}
