import { useActions, useValues } from 'kea'

import { IconBolt, IconPlus, IconPlusSmall, IconX } from '@posthog/icons'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Link } from 'lib/lemon-ui/Link'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { defaultEvaluationEnvironmentsLogic } from './defaultEvaluationEnvironmentsLogic'

export function DefaultEvaluationEnvironments(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const { tags, isEnabled, canAddMoreTags, newTagInput, defaultEvaluationEnvironmentsLoading, isAdding } = useValues(
        defaultEvaluationEnvironmentsLogic
    )
    const { addTag, removeTag, toggleEnabled, setNewTagInput, setIsAdding } = useActions(
        defaultEvaluationEnvironmentsLogic
    )

    // Check if feature flag is enabled
    if (!featureFlags[FEATURE_FLAGS.DEFAULT_EVALUATION_ENVIRONMENTS]) {
        return null
    }

    const handleAddTag = (): void => {
        const trimmedTag = newTagInput.trim().toLowerCase()
        if (trimmedTag && !tags.some((t: { name: string }) => t.name === trimmedTag)) {
            addTag(trimmedTag)
        }
    }

    const handleKeyDown = (e: React.KeyboardEvent): void => {
        if (e.key === 'Enter') {
            handleAddTag()
        } else if (e.key === 'Escape') {
            setIsAdding(false)
            setNewTagInput('')
        }
    }

    return (
        <div className="space-y-4">
            <div className="space-y-2">
                <h3 className="min-w-[25rem]">Default Evaluation Environments</h3>

                <p>
                    Configure default{' '}
                    <Link
                        to="https://posthog.com/docs/feature-flags/evaluation-environments"
                        target="_blank"
                        disableDocsPanel
                    >
                        evaluation environments
                    </Link>{' '}
                    that will be automatically applied to new feature flags. When enabled, these tags will be set on
                    newly created flags.
                </p>

                <LemonSwitch
                    data-attr="default-evaluation-environments-switch"
                    onChange={toggleEnabled}
                    label="Apply default evaluation environments to new flags"
                    bordered
                    checked={isEnabled}
                    disabled={defaultEvaluationEnvironmentsLoading}
                />
            </div>

            {isEnabled && (
                <div className="space-y-3">
                    <div>
                        <h4 className="text-sm font-semibold mb-2">Default Evaluation Tags</h4>
                        <p className="text-xs text-muted mb-3">
                            These tags will be automatically added as evaluation constraints to all new feature flags.
                            Users can still modify or remove them from individual flags during creation.
                        </p>
                    </div>

                    <div className="flex flex-wrap gap-2 items-center">
                        {tags.map((tag: { id: number; name: string }) => (
                            <LemonTag
                                key={tag.id}
                                type="success"
                                icon={<IconBolt />}
                                closable
                                onClose={() => removeTag(tag.name)}
                            >
                                {tag.name}
                            </LemonTag>
                        ))}

                        {isAdding ? (
                            <div className="inline-flex items-center gap-1">
                                <LemonInput
                                    size="small"
                                    value={newTagInput}
                                    onChange={setNewTagInput}
                                    onKeyDown={handleKeyDown}
                                    placeholder="e.g., production"
                                    autoFocus
                                    className="w-32"
                                />
                                <LemonButton
                                    size="small"
                                    type="primary"
                                    onClick={handleAddTag}
                                    disabled={!newTagInput.trim()}
                                    icon={<IconPlusSmall />}
                                />
                                <LemonButton
                                    size="small"
                                    onClick={() => {
                                        setIsAdding(false)
                                        setNewTagInput('')
                                    }}
                                    icon={<IconX />}
                                />
                            </div>
                        ) : (
                            canAddMoreTags && (
                                <LemonButton
                                    size="small"
                                    type="secondary"
                                    onClick={() => setIsAdding(true)}
                                    icon={<IconPlus />}
                                >
                                    Add tag
                                </LemonButton>
                            )
                        )}
                    </div>

                    {tags.length === 0 && !isAdding && (
                        <div className="text-sm text-muted italic">
                            No default evaluation tags configured. Add tags to automatically apply them to new flags.
                        </div>
                    )}

                    {tags.length >= 10 && (
                        <div className="text-xs text-warning">Maximum of 10 default evaluation tags allowed.</div>
                    )}
                </div>
            )}
        </div>
    )
}
