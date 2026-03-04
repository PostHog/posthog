import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import { IconBolt, IconCheck, IconPencil, IconPlus, IconX } from '@posthog/icons'

import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { colorForString } from 'lib/utils'

import { defaultEvaluationContextsLogic } from './defaultEvaluationContextsLogic'
import { featureFlagEvaluationTagsLogic } from './featureFlagEvaluationTagsLogic'
import { featureFlagLogic } from './featureFlagLogic'

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
    const { availableContexts } = useValues(defaultEvaluationContextsLogic)

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
        setLocalTags(newTags)
        if (onChange) {
            onChange(newTags, localEvaluationTags)
        }
    }

    const handleEvaluationContextsChange = (newContexts: string[]): void => {
        setLocalEvaluationTags(newContexts)
        if (onChange) {
            onChange(localTags, newContexts)
        }
    }

    if (isEditing) {
        const contextOptions = [...new Set([...availableContexts, ...localEvaluationTags])]
            .sort()
            .map((c: string) => ({ key: c, label: c }))

        return (
            <div className={clsx(className, 'flex flex-col gap-3')}>
                <div className="flex flex-col gap-1">
                    <div className="text-xs font-semibold">Tags</div>
                    <LemonInputSelect
                        mode="multiple"
                        allowCustomValues
                        value={localTags}
                        options={tagsAvailable?.map((t: string) => ({ key: t, label: t }))}
                        onChange={handleTagsChange}
                        loading={featureFlagLoading}
                        data-attr="feature-flag-tags-input"
                        placeholder='Add tags like "v2-launch", "experiment"'
                        autoFocus
                    />
                </div>

                <div className="flex flex-col gap-1">
                    <div className="text-xs font-semibold">Evaluation contexts</div>
                    <div className="text-xs text-muted">
                        Restrict where this flag evaluates at runtime (e.g., "production", "staging").
                    </div>
                    <LemonInputSelect
                        mode="multiple"
                        allowCustomValues
                        value={localEvaluationTags}
                        options={contextOptions}
                        onChange={handleEvaluationContextsChange}
                        loading={featureFlagLoading}
                        data-attr="feature-flag-evaluation-contexts-input"
                        placeholder='Add contexts like "production", "staging"'
                    />
                </div>

                {onSave && !onChange && (
                    <div className="flex gap-1">
                        <ButtonPrimitive
                            type="button"
                            variant="outline"
                            onClick={handleSave}
                            disabled={featureFlagLoading}
                            tooltip="Save"
                            aria-label="Save"
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
                tags.map((tag) => (
                    <LemonTag key={tag} type={colorForString(tag)}>
                        {tag}
                    </LemonTag>
                ))}

            {evaluationTags.length > 0 &&
                evaluationTags.map((ctx) => (
                    <Tooltip key={`ctx-${ctx}`} title="Evaluation context">
                        <LemonTag type="success" icon={<IconBolt />}>
                            {ctx}
                        </LemonTag>
                    </Tooltip>
                ))}

            {!staticOnly && (
                <LemonTag
                    type="none"
                    onClick={() => setIsEditing(true)}
                    data-attr="button-edit-tags"
                    icon={tags.length > 0 || evaluationTags.length > 0 ? <IconPencil /> : <IconPlus />}
                    className="border border-dashed cursor-pointer"
                    size="medium"
                >
                    {tags.length > 0 || evaluationTags.length > 0 ? 'Edit' : 'Add tags'}
                </LemonTag>
            )}
        </div>
    )
}
