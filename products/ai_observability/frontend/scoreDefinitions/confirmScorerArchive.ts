import { LemonDialog } from 'lib/lemon-ui/LemonDialog'

import { llmAnalyticsScoreDefinitionsRetrieve } from '../generated/api'
import type { ScoreDefinitionApi } from '../generated/api.schemas'

export async function confirmScorerArchive(teamId: string, definition: ScoreDefinitionApi): Promise<boolean> {
    const current = await llmAnalyticsScoreDefinitionsRetrieve(teamId, definition.id)
    const suites = current.assigned_suite_keys ?? current.suite_keys
    return new Promise((resolve) =>
        LemonDialog.open({
            title: `Archive ${current.name}?`,
            description: suites?.length
                ? `Future runs of ${suites.join(', ')} will lose their default experiment scorer. Existing runs keep their scores.`
                : 'Existing runs keep their scores. You can choose a new default for future runs.',
            primaryButton: { children: 'Archive scorer', status: 'danger', onClick: () => resolve(true) },
            secondaryButton: { children: 'Cancel' },
            onAfterClose: () => resolve(false),
            closeOnNavigate: true,
        })
    )
}
