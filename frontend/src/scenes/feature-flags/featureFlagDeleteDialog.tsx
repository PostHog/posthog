import { LemonDialog } from '@posthog/lemon-ui'

import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { FeatureFlagType } from '~/types'

import { DependentFlag } from './featureFlagLogic'

interface FeatureFlagDeleteBlocker {
    kind: string
    name: string
    url?: string
}

export function getFeatureFlagDeleteBlockers(
    featureFlag: Partial<FeatureFlagType>,
    dependentFlags: DependentFlag[] = []
): FeatureFlagDeleteBlocker[] {
    const blockers: FeatureFlagDeleteBlocker[] = []
    for (const feature of featureFlag.features || []) {
        blockers.push({
            kind: 'Early access feature',
            name: feature.name,
            url: urls.earlyAccessFeature(feature.id),
        })
    }
    for (const experiment of featureFlag.experiment_set_metadata || []) {
        if (experiment.is_running) {
            blockers.push({ kind: 'Running experiment', name: experiment.name, url: urls.experiment(experiment.id) })
        }
    }
    for (const survey of featureFlag.surveys || []) {
        blockers.push({ kind: 'Survey', name: survey.name, url: urls.survey(survey.id) })
    }
    if (featureFlag.is_used_in_replay_settings) {
        blockers.push({
            kind: 'Session replay',
            name: 'Recording conditions in replay settings',
            url: urls.settings('project-replay'),
        })
    }
    for (const flag of dependentFlags) {
        blockers.push({
            kind: 'Feature flag',
            name: flag.name || flag.key,
            url: urls.featureFlag(flag.id),
        })
    }
    return blockers
}

/**
 * Opens the delete confirmation dialog for a feature flag. If linked resources block deletion,
 * shows what's blocking it — with direct links — instead of the confirmation.
 */
export function openFeatureFlagDeleteDialog(
    featureFlag: Partial<FeatureFlagType>,
    onDelete: () => void,
    dependentFlags: DependentFlag[] = []
): void {
    const blockers = getFeatureFlagDeleteBlockers(featureFlag, dependentFlags)

    if (blockers.length > 0) {
        LemonDialog.open({
            title: "This feature flag can't be deleted yet",
            description: (
                <div className="deprecated-space-y-2">
                    <div>
                        <code>{featureFlag.key}</code> is still in use. Unlink or delete the following before deleting
                        this flag:
                    </div>
                    <ul className="list-disc pl-5">
                        {blockers.map((blocker, index) => (
                            <li key={index}>
                                {blocker.kind}:{' '}
                                {blocker.url ? (
                                    <Link to={blocker.url}>{blocker.name || 'Untitled'}</Link>
                                ) : (
                                    blocker.name
                                )}
                            </li>
                        ))}
                    </ul>
                </div>
            ),
            primaryButton: {
                children: 'Close',
                type: 'secondary',
                size: 'small',
            },
        })
        return
    }

    LemonDialog.open({
        title: 'Delete feature flag?',
        description: `Are you sure you want to delete "${featureFlag.key}"?`,
        primaryButton: {
            children: 'Delete',
            status: 'danger',
            onClick: onDelete,
            size: 'small',
        },
        secondaryButton: {
            children: 'Cancel',
            type: 'tertiary',
            size: 'small',
        },
    })
}
