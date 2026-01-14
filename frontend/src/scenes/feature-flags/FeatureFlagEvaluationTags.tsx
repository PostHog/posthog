import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import { IconBolt, IconCheck, IconPencil, IconPlus, IconX } from '@posthog/icons'

import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { colorForString } from 'lib/utils'

import { featureFlagEvaluationTagsLogic } from './featureFlagEvaluationTagsLogic'
import { featureFlagLogic } from './featureFlagLogic'

// Utility function to keep evaluation tags in sync with regular tags
const syncEvaluationTags = (tags: string[], evaluationTags: string[]): string[] =>
    evaluationTags.filter((tag) => tags.includes(tag))

interface FeatureFlagEvaluationTagsProps {
    tags: string[]
    evaluationTags: string[]
    tagsAvailable?: string[]
    className?: string
    flagId?: number | string | null
    /** Differentiates multiple instances for the same flag (e.g., 'sidebar' vs 'form') */
    context: 'sidebar' | 'form' | 'static'
    /** Form mode: parent handles persistence. Mutually exclusive with onSave. */
    onChange?: (tags: string[], evaluationTags: string[]) => void
    /** Sidebar mode: component handles persistence. Mutually exclusive with onChange. */
    onSave?: (tags: string[], evaluationTags: string[]) => void
}

export function FeatureFlagEvaluationTags({
    tags,
    evaluationTags,
    tagsAvailable,
    className,
    flagId,
    context,
    onChange,
    onSave,
}: FeatureFlagEvaluationTagsProps): JSX.Element {
    const staticOnly = context === 'static'
    const logic = featureFlagEvaluationTagsLogic({ flagId, context, tags, evaluationTags })
    const { isEditing, localTags, localEvaluationTags } = useValues(logic)
    const { setIsEditing, setLocalTags, setLocalEvaluationTags, saveTagsAndEvaluationTags, cancelEditing } =
        useActions(logic)

    const { featureFlagLoading } = useValues(featureFlagLogic)

    const handleSave = (): void => {
        if (onSave) {
            onSave(localTags, localEvaluationTags)
            setIsEditing(false)
        } else {
            saveTagsAndEvaluationTags()
        }
    }

    const handleCancel = (): void => {
        setLocalTags(tags)
        setLocalEvaluationTags(evaluationTags)
        cancelEditing()
    }

    const handleTagsChange = (newTags: string[]): void => {
        // Sync evaluation tags when tags change
        const syncedEvaluationTags = syncEvaluationTags(newTags, localEvaluationTags)

        setLocalTags(newTags)
        setLocalEvaluationTags(syncedEvaluationTags)

        if (onChange) {
            onChange(newTags, syncedEvaluationTags)
        }
    }

    const toggleEvaluationTag = (tag: string): void => {
        const newEvaluationTags = localEvaluationTags.includes(tag)
            ? localEvaluationTags.filter((t: string) => t !== tag)
            : [...localEvaluationTags, tag]

        setLocalEvaluationTags(newEvaluationTags)

        if (onChange) {
            onChange(localTags, newEvaluationTags)
        }
    }

    if (isEditing) {
        return (
            <div className={clsx(className, 'flex flex-col gap-2')}>
                <LemonInputSelect
                    mode="multiple"
                    allowCustomValues
                    value={localTags}
                    options={tagsAvailable?.map((t: string) => ({ key: t, label: t }))}
                    onChange={handleTagsChange}
                    loading={featureFlagLoading}
                    data-attr="feature-flag-tags-input"
                    placeholder='Add evaluation contexts like "marketing-page", "app", "docs"'
                    autoFocus
                />

                {localTags.length > 0 && (
                    <div className="bg-border-light rounded p-2">
                        <div className="text-xs text-muted mb-2">
                            Select which tags should act as evaluation contexts. Flags tagged with evaluation contexts
                            will only evaluate when the SDK is initialized with matching environment tags, providing
                            fine-grained runtime control over flag evaluation.
                        </div>
                        <div className="flex flex-col gap-1">
                            {localTags.map((tag: string) => (
                                <LemonCheckbox
                                    key={tag}
                                    checked={localEvaluationTags.includes(tag)}
                                    onChange={() => toggleEvaluationTag(tag)}
                                    label={<span className="text-sm">Use "{tag}" as evaluation context</span>}
                                />
                            ))}
                        </div>
                    </div>
                )}

                {onSave && !onChange && (
                    <div className="flex gap-1">
                        <ButtonPrimitive
                            type="button"
                            variant="outline"
                            onClick={handleSave}
                            disabled={featureFlagLoading}
                            tooltip="Save tags"
                            aria-label="Save tags"
                        >
                            <IconCheck />
                        </ButtonPrimitive>
                        <ButtonPrimitive
                            type="button"
                            variant="outline"
                            onClick={handleCancel}
                            tooltip="Cancel editing"
                            aria-label="Cancel editing"
                        >
                            <IconX />
                        </ButtonPrimitive>
                    </div>
                )}
            </div>
        )
    }

    return (
        <div className={clsx(className, 'inline-flex flex-wrap gap-1 items-center')}>
            {tags.length > 0 &&
                tags.map((tag) => {
                    const isEvaluationTag = evaluationTags.includes(tag)
                    return (
                        <Tooltip
                            key={tag}
                            title={isEvaluationTag ? 'This tag is used as an evaluation context' : undefined}
                        >
                            <LemonTag
                                type={isEvaluationTag ? 'success' : colorForString(tag)}
                                icon={isEvaluationTag ? <IconBolt /> : undefined}
                            >
                                {tag}
                            </LemonTag>
                        </Tooltip>
                    )
                })}

            {!staticOnly && (
                <LemonTag
                    type="none"
                    onClick={() => setIsEditing(true)}
                    data-attr="button-edit-tags"
                    icon={tags.length > 0 ? <IconPencil /> : <IconPlus />}
                    className="border border-dashed cursor-pointer"
                    size="medium"
                >
                    {tags.length > 0 ? 'Edit' : 'Add tags'}
                </LemonTag>
            )}
        </div>
    )
}
