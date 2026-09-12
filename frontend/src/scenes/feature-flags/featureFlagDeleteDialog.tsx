import { router } from 'kea-router'

import { LemonDialog } from '@posthog/lemon-ui'

import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { FeatureFlagType } from '~/types'

import { DependentFlag } from './featureFlagLogic'

interface FeatureFlagDeleteBlocker {
    kind: string
    name: string
    url?: string
    actionLabel?: string
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
            actionLabel: 'Go to early access feature',
        })
    }
    for (const experiment of featureFlag.experiment_set_metadata || []) {
        if (experiment.is_running) {
            blockers.push({
                kind: 'Running experiment',
                name: experiment.name,
                url: urls.experiment(experiment.id),
                actionLabel: 'Go to experiment',
            })
        }
    }
    for (const survey of featureFlag.surveys || []) {
        blockers.push({ kind: 'Survey', name: survey.name, url: urls.survey(survey.id), actionLabel: 'Go to survey' })
    }
    if (featureFlag.is_used_in_replay_settings) {
        blockers.push({
            kind: 'Session replay',
            name: 'Recording conditions in replay settings',
            url: urls.settings('project-replay'),
            actionLabel: 'Go to replay settings',
        })
    }
    for (const flag of dependentFlags) {
        blockers.push({
            kind: 'Feature flag',
            name: flag.name || flag.key,
            url: urls.featureFlag(flag.id),
            actionLabel: 'Go to feature flag',
        })
    }
    return blockers
}

/**
 * A single blocker can be resolved in one click, so the dialog sends the user straight there.
 * With several, the listed links are the only sensible route.
 */
export function getFeatureFlagDeleteBlockerAction(
    blockers: FeatureFlagDeleteBlocker[]
): { label: string; url: string } | null {
    if (blockers.length !== 1) {
        return null
    }
    const [blocker] = blockers
    return blocker.url && blocker.actionLabel ? { label: blocker.actionLabel, url: blocker.url } : null
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
        const blockerAction = getFeatureFlagDeleteBlockerAction(blockers)
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
            primaryButton: blockerAction
                ? {
                      children: blockerAction.label,
                      type: 'primary',
                      size: 'small',
                      onClick: () => router.actions.push(blockerAction.url),
                  }
                : {
                      children: 'Close',
                      type: 'secondary',
                      size: 'small',
                  },
            secondaryButton: blockerAction
                ? {
                      children: 'Close',
                      type: 'tertiary',
                      size: 'small',
                  }
                : undefined,
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
