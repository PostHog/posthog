import { useActions, useValues } from 'kea'

import { IconBolt, IconPlus, IconPlusSmall, IconX } from '@posthog/icons'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { FEATURE_FLAGS, TeamMembershipLevel } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { defaultEvaluationContextsLogic } from './defaultEvaluationContextsLogic'

export function DefaultEvaluationContexts(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const { contexts, isEnabled, canAddMoreContexts, newContextInput, defaultEvaluationContextsLoading, isAdding } =
        useValues(defaultEvaluationContextsLogic)
    const { addContext, removeContext, toggleEnabled, setNewContextInput, setIsAdding } =
        useActions(defaultEvaluationContextsLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    if (!featureFlags[FEATURE_FLAGS.DEFAULT_EVALUATION_ENVIRONMENTS]) {
        return null
    }

    const handleAddContext = (): void => {
        const trimmed = newContextInput.trim().toLowerCase()
        if (trimmed && !contexts.some((c: { name: string }) => c.name === trimmed)) {
            addContext(trimmed)
        }
    }

    const handleKeyDown = (e: React.KeyboardEvent): void => {
        if (e.key === 'Enter') {
            handleAddContext()
        } else if (e.key === 'Escape') {
            setIsAdding(false)
            setNewContextInput('')
        }
    }

    return (
        <div className="space-y-4">
            <LemonSwitch
                data-attr="default-evaluation-contexts-switch"
                onChange={toggleEnabled}
                label="Apply default evaluation contexts to new flags"
                bordered
                checked={isEnabled}
                disabled={defaultEvaluationContextsLoading}
                disabledReason={restrictedReason}
            />

            {isEnabled && (
                <div className="space-y-3">
                    <div className="flex flex-wrap gap-2 items-center">
                        {contexts.map((ctx: { id: number | string; name: string }) => (
                            <LemonTag
                                key={ctx.id}
                                type="success"
                                icon={<IconBolt />}
                                closable
                                onClose={() => removeContext(ctx.name)}
                            >
                                {ctx.name}
                            </LemonTag>
                        ))}

                        {isAdding ? (
                            <div className="inline-flex items-center gap-1">
                                <LemonInput
                                    size="small"
                                    value={newContextInput}
                                    onChange={setNewContextInput}
                                    onKeyDown={handleKeyDown}
                                    placeholder="e.g., main-app"
                                    autoFocus
                                    className="w-32"
                                    disabledReason={restrictedReason}
                                />
                                <LemonButton
                                    size="small"
                                    type="primary"
                                    onClick={handleAddContext}
                                    disabled={!newContextInput.trim()}
                                    icon={<IconPlusSmall />}
                                    disabledReason={restrictedReason}
                                />
                                <LemonButton
                                    size="small"
                                    onClick={() => {
                                        setIsAdding(false)
                                        setNewContextInput('')
                                    }}
                                    icon={<IconX />}
                                    disabledReason={restrictedReason}
                                />
                            </div>
                        ) : (
                            canAddMoreContexts && (
                                <LemonButton
                                    size="small"
                                    type="secondary"
                                    onClick={() => setIsAdding(true)}
                                    icon={<IconPlus />}
                                    disabledReason={restrictedReason}
                                >
                                    Add context
                                </LemonButton>
                            )
                        )}
                    </div>

                    {contexts.length === 0 && !isAdding && (
                        <div className="text-sm text-muted italic">
                            No default evaluation contexts configured. Add contexts to automatically apply them to new
                            flags.
                        </div>
                    )}

                    {contexts.length >= 10 && (
                        <div className="text-xs text-warning">Maximum of 10 default evaluation contexts allowed.</div>
                    )}
                </div>
            )}
        </div>
    )
}
