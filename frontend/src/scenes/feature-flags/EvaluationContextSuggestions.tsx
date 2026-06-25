import { useActions, useValues } from 'kea'

import { IconUndo, IconX } from '@posthog/icons'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { FEATURE_FLAGS, TeamMembershipLevel } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { defaultEvaluationContextsLogic } from './defaultEvaluationContextsLogic'

export function EvaluationContextSuggestions(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const { availableContexts, hiddenContexts, pendingContextName } = useValues(defaultEvaluationContextsLogic)
    const { hideContext, unhideContext } = useActions(defaultEvaluationContextsLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    if (!featureFlags[FEATURE_FLAGS.FLAG_EVALUATION_TAGS]) {
        return null
    }

    return (
        <div className="space-y-4">
            <p className="text-sm text-muted">
                These names are suggested when scoping a flag to evaluation contexts. Hiding a name only removes it from
                the suggestion list — flags already using it keep working, and hidden names stay hidden until restored
                from this settings page.
            </p>

            <div className="flex flex-col gap-2">
                <h4 className="mb-0">Suggested contexts</h4>
                {availableContexts.length === 0 ? (
                    <div className="text-sm text-muted italic">No suggested evaluation contexts.</div>
                ) : (
                    <div className="flex flex-wrap gap-2 items-center">
                        {availableContexts.map((name) => (
                            <LemonTag key={name} type="default">
                                <span className="flex items-center gap-1">
                                    {name}
                                    <LemonButton
                                        size="xsmall"
                                        icon={<IconX />}
                                        tooltip={`Hide "${name}" from suggestions`}
                                        onClick={() => hideContext(name)}
                                        disabledReason={
                                            restrictedReason ?? (pendingContextName ? 'Saving…' : undefined)
                                        }
                                        loading={pendingContextName === name}
                                    />
                                </span>
                            </LemonTag>
                        ))}
                    </div>
                )}
            </div>

            {hiddenContexts.length > 0 && (
                <div className="flex flex-col gap-2">
                    <h4 className="mb-0">Hidden from suggestions</h4>
                    <div className="flex flex-wrap gap-2 items-center">
                        {hiddenContexts.map((name) => (
                            <LemonTag key={name} type="muted">
                                <span className="flex items-center gap-1">
                                    {name}
                                    <LemonButton
                                        size="xsmall"
                                        icon={<IconUndo />}
                                        tooltip="Restore to suggestions"
                                        onClick={() => unhideContext(name)}
                                        disabledReason={
                                            restrictedReason ?? (pendingContextName ? 'Saving…' : undefined)
                                        }
                                        loading={pendingContextName === name}
                                    />
                                </span>
                            </LemonTag>
                        ))}
                    </div>
                </div>
            )}
        </div>
    )
}
