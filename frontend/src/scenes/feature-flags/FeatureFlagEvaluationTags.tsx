import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import { IconCheck, IconInfo, IconPencil, IconPlus, IconX } from '@posthog/icons'

import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Link } from 'lib/lemon-ui/Link'
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
    const { isEditingTags, isEditingContexts, localTags, localEvaluationTags } = useValues(logic)
    const {
        setIsEditingTags,
        setIsEditingContexts,
        setLocalTags,
        setLocalEvaluationTags,
        saveTags,
        saveContexts,
        cancelEditingTags,
        cancelEditingContexts,
    } = useActions(logic)

    const { featureFlagLoading } = useValues(featureFlagLogic)
    const { availableContexts } = useValues(defaultEvaluationContextsLogic)

    const handleSaveTags = (): void => {
        if (onSave) {
            onSave(localTags, evaluationTags)
            setIsEditingTags(false)
        } else {
            saveTags()
        }
    }

    const handleSaveContexts = (): void => {
        if (onSave) {
            onSave(tags, localEvaluationTags)
            setIsEditingContexts(false)
        } else {
            saveContexts()
        }
    }

    const handleCancelTags = (): void => {
        setLocalTags(tags)
        cancelEditingTags()
    }

    const handleCancelContexts = (): void => {
        setLocalEvaluationTags(evaluationTags)
        cancelEditingContexts()
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

    const contextOptions = [...new Set([...availableContexts, ...localEvaluationTags])]
        .sort()
        .map((c: string) => ({ key: c, label: c }))

    return (
        <div className={clsx(className, 'flex flex-col gap-3')}>
            {/* Tags section */}
            <div className="flex flex-col gap-1">
                <div className="text-sm font-medium">Tags</div>
                {isEditingTags ? (
                    <>
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
                        {onSave && !onChange && (
                            <div className="flex gap-1 mt-1">
                                <ButtonPrimitive
                                    type="button"
                                    variant="outline"
                                    onClick={handleSaveTags}
                                    disabled={featureFlagLoading}
                                    tooltip="Save tags"
                                    aria-label="Save tags"
                                >
                                    <IconCheck />
                                </ButtonPrimitive>
                                <ButtonPrimitive
                                    type="button"
                                    variant="outline"
                                    onClick={handleCancelTags}
                                    tooltip="Cancel editing tags"
                                    aria-label="Cancel editing tags"
                                >
                                    <IconX />
                                </ButtonPrimitive>
                            </div>
                        )}
                    </>
                ) : (
                    <div className="inline-flex flex-wrap gap-1 items-center">
                        {tags.length > 0 ? (
                            tags.map((tag) => (
                                <LemonTag key={tag} type={colorForString(tag)}>
                                    {tag}
                                </LemonTag>
                            ))
                        ) : (
                            <span className="text-muted text-xs">No tags</span>
                        )}
                        {!staticOnly && (
                            <LemonTag
                                type="none"
                                onClick={() => setIsEditingTags(true)}
                                data-attr="button-edit-tags"
                                icon={tags.length > 0 ? <IconPencil /> : <IconPlus />}
                                className="border border-dashed cursor-pointer"
                                size="medium"
                            >
                                {tags.length > 0 ? 'Edit' : 'Add'}
                            </LemonTag>
                        )}
                    </div>
                )}
            </div>

            <LemonDivider className="my-0" />

            {/* Evaluation contexts section */}
            <div className="flex flex-col gap-1">
                <span className="text-sm font-medium inline-flex items-center gap-1">
                    Evaluation contexts
                    {(context === 'form' || isEditingContexts) && (
                        <Tooltip
                            interactive
                            title={
                                <>
                                    Control where this flag evaluates by matching SDK-declared contexts.{' '}
                                    <Link
                                        to="https://posthog.com/docs/feature-flags/evaluation-contexts"
                                        target="_blank"
                                    >
                                        Learn more
                                    </Link>
                                </>
                            }
                        >
                            <IconInfo className="text-xl text-secondary shrink-0" />
                        </Tooltip>
                    )}
                </span>
                {isEditingContexts ? (
                    <>
                        <div className="text-xs text-muted">
                            Only evaluate this flag when the SDK declares a matching context (e.g., "main-app",
                            "marketing-site").
                        </div>
                        <LemonInputSelect
                            mode="multiple"
                            allowCustomValues
                            value={localEvaluationTags}
                            options={contextOptions}
                            onChange={handleEvaluationContextsChange}
                            loading={featureFlagLoading}
                            data-attr="feature-flag-evaluation-contexts-input"
                            placeholder='Add contexts like "main-app", "marketing-site"'
                            autoFocus
                        />
                        {onSave && !onChange && (
                            <div className="flex gap-1 mt-1">
                                <ButtonPrimitive
                                    type="button"
                                    variant="outline"
                                    onClick={handleSaveContexts}
                                    disabled={featureFlagLoading}
                                    tooltip="Save evaluation contexts"
                                    aria-label="Save evaluation contexts"
                                >
                                    <IconCheck />
                                </ButtonPrimitive>
                                <ButtonPrimitive
                                    type="button"
                                    variant="outline"
                                    onClick={handleCancelContexts}
                                    tooltip="Cancel editing evaluation contexts"
                                    aria-label="Cancel editing evaluation contexts"
                                >
                                    <IconX />
                                </ButtonPrimitive>
                            </div>
                        )}
                    </>
                ) : (
                    <div className="inline-flex flex-wrap gap-1 items-center">
                        {evaluationTags.length > 0 ? (
                            evaluationTags.map((ctx) => (
                                <div
                                    key={`ctx-${ctx}`}
                                    className="inline-flex items-center rounded px-2 py-1 bg-bg-light border border-border"
                                >
                                    <span className="font-mono text-xs">{ctx}</span>
                                </div>
                            ))
                        ) : (
                            <span className="text-muted text-xs">No contexts</span>
                        )}
                        {!staticOnly && (
                            <LemonTag
                                type="none"
                                onClick={() => setIsEditingContexts(true)}
                                data-attr="button-edit-evaluation-contexts"
                                icon={evaluationTags.length > 0 ? <IconPencil /> : <IconPlus />}
                                className="border border-dashed cursor-pointer"
                                size="medium"
                            >
                                {evaluationTags.length > 0 ? 'Edit' : 'Add'}
                            </LemonTag>
                        )}
                    </div>
                )}
            </div>
        </div>
    )
}
