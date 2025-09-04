import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconBolt, IconPencil, IconPlus } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { colorForString } from 'lib/utils'

import { featureFlagEvaluationTagsLogic } from './featureFlagEvaluationTagsLogic'
import { featureFlagLogic } from './featureFlagLogic'

interface FeatureFlagEvaluationTagsProps {
    tags: string[]
    evaluationTags: string[]
    onChange?: (tags: string[], evaluationTags: string[]) => void
    tagsAvailable?: string[]
    staticOnly?: boolean
    className?: string
}

export function FeatureFlagEvaluationTags({
    tags,
    evaluationTags,
    onChange,
    tagsAvailable,
    staticOnly = false,
    className,
}: FeatureFlagEvaluationTagsProps): JSX.Element {
    const logic = featureFlagEvaluationTagsLogic({ tags, evaluationTags })
    const { editingTags, showEvaluationOptions, selectedTags, selectedEvaluationTags } = useValues(logic)
    const {
        setEditingTags,
        setShowEvaluationOptions,
        setSelectedTags,
        setSelectedEvaluationTags,
        resetSelectionsToProps,
    } = useActions(logic)

    const { saveFeatureFlag } = useActions(featureFlagLogic)
    const { featureFlagLoading } = useValues(featureFlagLogic)

    // Keep selections fresh when props change while not editing
    useEffect(() => {
        if (!editingTags) {
            resetSelectionsToProps()
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [tags.join(','), evaluationTags.join(','), editingTags])

    const handleSave = (): void => {
        if (onChange) {
            onChange(selectedTags, selectedEvaluationTags)
        } else {
            saveFeatureFlag({
                tags: selectedTags,
                evaluation_tags: selectedEvaluationTags,
            })
        }
        setEditingTags(false)
        setShowEvaluationOptions(false)
    }

    const toggleEvaluationTag = (tag: string): void => {
        if (selectedEvaluationTags.includes(tag)) {
            setSelectedEvaluationTags(selectedEvaluationTags.filter((t: string) => t !== tag))
        } else {
            setSelectedEvaluationTags([...selectedEvaluationTags, tag])
        }
    }

    if (editingTags) {
        return (
            <div className={clsx(className, 'flex flex-col gap-2')}>
                <div className="flex items-center gap-2">
                    <LemonInputSelect
                        mode="multiple"
                        allowCustomValues
                        value={selectedTags}
                        options={tagsAvailable?.map((t: string) => ({ key: t, label: t }))}
                        onChange={setSelectedTags}
                        loading={featureFlagLoading}
                        data-attr="feature-flag-tags-input"
                        placeholder='Add tags like "production", "app", "docs-page"'
                        autoFocus
                    />
                    {selectedTags.length > 0 && (
                        <LemonButton
                            size="small"
                            onClick={() => setShowEvaluationOptions(!showEvaluationOptions)}
                            icon={<IconBolt />}
                            tooltip="Configure evaluation environments"
                        />
                    )}
                </div>

                {showEvaluationOptions && selectedTags.length > 0 && (
                    <div className="bg-border-light rounded p-2">
                        <div className="text-xs text-muted mb-2">
                            Select which tags should also act as evaluation constraints. Flags with evaluation tags will
                            only evaluate when the SDK provides matching environment tags.
                        </div>
                        <div className="flex flex-col gap-1">
                            {selectedTags.map((tag: string) => (
                                <LemonCheckbox
                                    key={tag}
                                    checked={selectedEvaluationTags.includes(tag)}
                                    onChange={() => toggleEvaluationTag(tag)}
                                    label={<span className="text-sm">Use "{tag}" as evaluation environment</span>}
                                />
                            ))}
                        </div>
                    </div>
                )}

                <div className="flex gap-2">
                    <LemonButton size="small" type="primary" onClick={handleSave} loading={featureFlagLoading}>
                        Save
                    </LemonButton>
                    <LemonButton
                        size="small"
                        onClick={() => {
                            setEditingTags(false)
                            setShowEvaluationOptions(false)
                            setSelectedTags(tags)
                            setSelectedEvaluationTags(evaluationTags)
                        }}
                    >
                        Cancel
                    </LemonButton>
                </div>
            </div>
        )
    }

    return (
        <div className={clsx(className, 'inline-flex flex-wrap gap-1 items-center')}>
            {tags.length > 0 &&
                tags.map((tag, index) => {
                    const isEvaluationTag = evaluationTags.includes(tag)
                    return (
                        <Tooltip
                            key={index}
                            title={
                                isEvaluationTag ? 'This tag acts as an evaluation environment constraint' : undefined
                            }
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
                    onClick={() => setEditingTags(true)}
                    data-attr="button-edit-tags"
                    icon={tags.length > 0 ? <IconPencil /> : <IconPlus />}
                    className="border border-dashed cursor-pointer"
                    size="small"
                >
                    {tags.length > 0 ? 'Edit' : 'Add tags'}
                </LemonTag>
            )}
        </div>
    )
}
