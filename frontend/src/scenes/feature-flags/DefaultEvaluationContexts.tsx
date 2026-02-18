import { useActions, useValues } from 'kea'

import { IconBolt, IconPlus, IconPlusSmall, IconX } from '@posthog/icons'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { defaultEvaluationContextsLogic } from './defaultEvaluationContextsLogic'

export function DefaultEvaluationContexts(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const { tags, isEnabled, canAddMoreTags, newTagInput, defaultEvaluationContextsLoading, isAdding } =
        useValues(defaultEvaluationContextsLogic)
    const { addTag, removeTag, toggleEnabled, setNewTagInput, setIsAdding } = useActions(defaultEvaluationContextsLogic)

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
            <LemonSwitch
                data-attr="default-evaluation-contexts-switch"
                onChange={toggleEnabled}
                label="Apply default evaluation contexts to new flags"
                bordered
                checked={isEnabled}
                disabled={defaultEvaluationContextsLoading}
            />

            {isEnabled && (
                <div className="space-y-3">
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
