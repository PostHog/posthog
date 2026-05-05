import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { useEffect, useState } from 'react'

import { IconPencil, IconPlus, IconX } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSkeleton, LemonTextArea } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { LemonField } from 'lib/lemon-ui/LemonField'
import {
    CUSTOM_TAG_DESCRIPTION_MAX_LENGTH,
    CUSTOM_TAG_NAME_MAX_LENGTH,
    CUSTOM_TAG_NAME_REGEX,
    CUSTOM_TAGS_MAX_COUNT,
    type CustomTagFormEntry,
    sessionSummariesConfigLogic,
} from 'scenes/session-recordings/player/sessionSummariesConfigLogic'

const PRODUCT_CONTEXT_PLACEHOLDER = `Example:

We're a B2B project management tool for software teams. Key events include creating projects, inviting team members, and completing sprints. A "Workspace" is a team's shared environment.

Free users see an upgrade modal when they try to export. This is intentional, not an error.

Users often switch between board view and list view rapidly when comparing tasks. This is normal behavior, not confusion.`

const EMPTY_DRAFT: CustomTagFormEntry = { name: '', description: '' }

function CustomTagsField({ disabled }: { disabled: boolean }): JSX.Element {
    const { configForm } = useValues(sessionSummariesConfigLogic)
    const { setConfigFormValue } = useActions(sessionSummariesConfigLogic)
    const tags = configForm.custom_tags
    const atCap = tags.length >= CUSTOM_TAGS_MAX_COUNT

    const [editingIndex, setEditingIndex] = useState<number | null>(null)
    const [draft, setDraft] = useState<CustomTagFormEntry>(EMPTY_DRAFT)

    const trimmedName = draft.name.trim()
    const trimmedDescription = draft.description.trim()
    const nameValid = CUSTOM_TAG_NAME_REGEX.test(trimmedName)
    const duplicate = !!trimmedName && tags.some((tag, i) => tag.name === trimmedName && i !== editingIndex)
    const canSubmit = nameValid && !!trimmedDescription && !duplicate && (editingIndex !== null || !atCap)

    const removeTag = (index: number): void => {
        setConfigFormValue(
            'custom_tags',
            tags.filter((_, i) => i !== index)
        )
        if (editingIndex === index) {
            setEditingIndex(null)
            setDraft(EMPTY_DRAFT)
        }
    }

    const beginEdit = (index: number): void => {
        setEditingIndex(index)
        setDraft(tags[index])
    }

    const cancelEdit = (): void => {
        setEditingIndex(null)
        setDraft(EMPTY_DRAFT)
    }

    const submit = (): void => {
        if (!canSubmit) {
            return
        }
        const next = { name: trimmedName, description: trimmedDescription }
        if (editingIndex === null) {
            setConfigFormValue('custom_tags', [...tags, next])
        } else {
            setConfigFormValue(
                'custom_tags',
                tags.map((tag, i) => (i === editingIndex ? next : tag))
            )
        }
        setEditingIndex(null)
        setDraft(EMPTY_DRAFT)
    }

    return (
        <div className="deprecated-space-y-3">
            <div>
                <div className="font-semibold">Custom tags</div>
                <p className="text-sm text-muted-alt mb-0">
                    Add up to {CUSTOM_TAGS_MAX_COUNT} of your own tags. Use snake_case for the tag name and add a
                    description so the AI knows when to apply it.
                </p>
            </div>

            {tags.length > 0 && (
                <div className="flex flex-wrap gap-2">
                    {tags.map((tag, i) => {
                        const isEditing = editingIndex === i
                        return (
                            <div
                                key={i}
                                className={`flex items-center gap-2 rounded border border-warning px-2 py-1 ${
                                    isEditing ? 'bg-warning/20' : 'bg-warning/10'
                                }`}
                            >
                                <span className="font-mono text-xs font-semibold text-warning">{tag.name}</span>
                                <span className="text-xs text-muted-alt max-w-[280px] truncate" title={tag.description}>
                                    {tag.description}
                                </span>
                                <LemonButton
                                    icon={<IconPencil />}
                                    size="xsmall"
                                    onClick={() => beginEdit(i)}
                                    disabled={disabled}
                                    aria-label="Edit tag"
                                />
                                <LemonButton
                                    icon={<IconX />}
                                    size="xsmall"
                                    onClick={() => removeTag(i)}
                                    disabled={disabled}
                                    aria-label="Remove tag"
                                />
                            </div>
                        )
                    })}
                </div>
            )}

            <div className="flex flex-col gap-2 rounded border bg-surface-primary p-3">
                <div className="text-sm font-semibold">{editingIndex !== null ? 'Edit tag' : 'Add a new tag'}</div>
                <div className="flex gap-2 items-start">
                    <div className="w-48 shrink-0">
                        <LemonInput
                            value={draft.name}
                            onChange={(value) => setDraft({ ...draft, name: value })}
                            placeholder="tag_name"
                            maxLength={CUSTOM_TAG_NAME_MAX_LENGTH}
                            disabled={disabled}
                            status={trimmedName && (!nameValid || duplicate) ? 'danger' : undefined}
                        />
                        {trimmedName && !nameValid && <div className="text-xs text-danger mt-1">Use snake_case.</div>}
                        {duplicate && (
                            <div className="text-xs text-danger mt-1">A tag with this name already exists.</div>
                        )}
                    </div>
                    <div className="flex-1">
                        <LemonInput
                            value={draft.description}
                            onChange={(value) => setDraft({ ...draft, description: value })}
                            placeholder="When the AI should apply this tag"
                            maxLength={CUSTOM_TAG_DESCRIPTION_MAX_LENGTH}
                            disabled={disabled}
                        />
                    </div>
                </div>
                <div className="flex gap-2 justify-end">
                    {editingIndex !== null && (
                        <LemonButton type="secondary" size="small" onClick={cancelEdit} disabled={disabled}>
                            Cancel
                        </LemonButton>
                    )}
                    <LemonButton
                        type="primary"
                        size="small"
                        icon={editingIndex === null ? <IconPlus /> : undefined}
                        onClick={submit}
                        disabledReason={
                            atCap && editingIndex === null
                                ? 'Tag limit reached'
                                : !canSubmit
                                  ? 'Fill in a valid name and description'
                                  : undefined
                        }
                        disabled={disabled}
                    >
                        {editingIndex === null ? 'Add tag' : 'Save changes'}
                    </LemonButton>
                </div>
            </div>
        </div>
    )
}

export function SessionSummariesSettings(): JSX.Element {
    const { isLoading, isUpdating } = useValues(sessionSummariesConfigLogic)
    const { revertConfigForm } = useActions(sessionSummariesConfigLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    useEffect(() => {
        revertConfigForm()
    }, [revertConfigForm])

    return (
        <Form logic={sessionSummariesConfigLogic} formKey="configForm" enableFormOnSubmit>
            <div className="deprecated-space-y-4">
                {isLoading ? (
                    <div className="gap-2 flex flex-col">
                        <LemonSkeleton className="h-6 w-32" />
                        <LemonSkeleton className="h-48" />
                    </div>
                ) : (
                    <>
                        <LemonField name="product_context" label="Product context">
                            <LemonTextArea
                                placeholder={PRODUCT_CONTEXT_PLACEHOLDER}
                                maxLength={10000}
                                minRows={10}
                                maxRows={24}
                                disabled={!!restrictedReason}
                            />
                        </LemonField>
                        <CustomTagsField disabled={!!restrictedReason} />
                    </>
                )}
                <div className="flex justify-end">
                    <LemonButton
                        type="primary"
                        htmlType="submit"
                        disabledReason={isLoading ? 'Loading…' : restrictedReason}
                        loading={isUpdating}
                    >
                        Save
                    </LemonButton>
                </div>
            </div>
        </Form>
    )
}
