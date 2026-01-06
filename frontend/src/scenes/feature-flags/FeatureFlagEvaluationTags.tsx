import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

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
    onChange?: (tags: string[], evaluationTags: string[]) => void
    onSave?: (tags: string[], evaluationTags: string[]) => void
    tagsAvailable?: string[]
    staticOnly?: boolean
    className?: string
    flagId?: number | string | null
}

export function FeatureFlagEvaluationTags({
    tags,
    evaluationTags,
    onChange,
    onSave,
    tagsAvailable,
    staticOnly = false,
    className,
    flagId,
}: FeatureFlagEvaluationTagsProps): JSX.Element {
    const instanceId = useMemo(() => Math.random().toString(36).substring(7), [])

    const logic = featureFlagEvaluationTagsLogic({ flagId, instanceId, tags, evaluationTags })
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
                    placeholder='Add tags like "production", "app", "docs-page"'
                    autoFocus
                />

                {localTags.length > 0 && (
                    <div className="bg-border-light rounded p-2">
                        <div className="text-xs text-muted mb-2">
                            Select which tags should also act as evaluation constraints. Flags with evaluation tags will
                            only evaluate when the SDK provides matching environment tags.
                        </div>
                        <div className="flex flex-col gap-1">
                            {localTags.map((tag: string) => (
                                <LemonCheckbox
                                    key={tag}
                                    checked={localEvaluationTags.includes(tag)}
                                    onChange={() => toggleEvaluationTag(tag)}
                                    label={<span className="text-sm">Use "{tag}" as evaluation tag</span>}
                                />
                            ))}
                        </div>
                    </div>
                )}

                {!onChange && onSave && (
                    <div className="flex gap-1">
                        <ButtonPrimitive
                            type="button"
                            variant="outline"
                            onClick={handleSave}
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
                        <Tooltip key={tag} title={isEvaluationTag ? 'This tag acts as an evaluation tag' : undefined}>
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
