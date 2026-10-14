import { IconEllipsis } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import type { ScoreDefinitionApi } from '../generated/api.schemas'

export function ScoreDefinitionActions({
    definition,
    archiving,
    showHistory,
    toggleArchive,
}: {
    definition: ScoreDefinitionApi
    archiving: boolean
    showHistory: boolean
    toggleArchive: (definition: ScoreDefinitionApi) => void
}): JSX.Element {
    const editDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.LlmAnalytics,
        AccessControlLevel.Editor
    )
    return (
        <LemonMenu
            items={[
                {
                    label: 'Edit scorer',
                    to: urls.aiObservabilityScorer(definition.id),
                    'data-attr': 'llma-scorer-edit-config',
                },
                ...(showHistory
                    ? [{ label: 'Offline history', to: urls.aiObservabilityOfflineScorerHistory(definition.id) }]
                    : []),
                {
                    label: 'Duplicate',
                    to: urls.aiObservabilityScorer('new', { duplicate: definition.id }),
                    disabledReason: editDisabledReason,
                    'data-attr': 'llma-scorer-duplicate',
                },
                {
                    label: definition.archived ? 'Unarchive' : 'Archive',
                    onClick: () => toggleArchive(definition),
                    disabledReason: editDisabledReason || (archiving ? 'Updating scorer' : undefined),
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
    )
}
