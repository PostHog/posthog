import { useActions, useValues } from 'kea'

import { IconPlus, IconTrash } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonCheckbox, LemonSelect } from '@posthog/lemon-ui'

import { getSeriesColor } from 'lib/colors'
import { LemonModalContent, LemonModalFooter, LemonModalHeader } from 'lib/lemon-ui/LemonModal/LemonModal'
import { LemonModal } from 'lib/lemon-ui/LemonModal/LemonModal'

import type { TemplatesEnumApi } from '../../../experiments/frontend/generated/api.schemas'
import { MAX_VERSIONS, createPromptExperimentModalLogic } from './createPromptExperimentModalLogic'

// Mirrors the variant-key generation in products/experiments/backend/presentation/views.py
// (_build_prompt_variants). Labels are the literal variant keys so the modal matches what
// gets stored on the feature flag.
function variantLabel(index: number, total: number): string {
    if (index === 0) {
        return 'control'
    }
    if (total === 2) {
        return 'test'
    }
    return `test-${index}`
}

export function CreatePromptExperimentModal(): JSX.Element | null {
    const {
        isModalOpen,
        promptName,
        promptVersions,
        versionSlots,
        selectedTemplates,
        templates,
        templatesLoading,
        canSubmit,
        isSubmitting,
        disabledVersionsByIndex,
        canAddSlot,
    } = useValues(createPromptExperimentModalLogic)
    const { closeModal, setVersionAt, addVersionSlot, removeVersionSlot, toggleTemplate, submitCreate } = useActions(
        createPromptExperimentModalLogic
    )

    if (!isModalOpen) {
        return null
    }

    return (
        <LemonModal isOpen onClose={closeModal} simple maxWidth="38rem">
            <LemonModalHeader>
                <h3>Create experiment{promptName ? ` for "${promptName}"` : ''}</h3>
            </LemonModalHeader>

            <LemonModalContent className="space-y-6">
                {promptVersions.length < 2 ? (
                    <LemonBanner type="warning">
                        This prompt has fewer than two versions. Publish another version before creating an experiment.
                    </LemonBanner>
                ) : null}

                <div className="space-y-3">
                    <label className="text-sm font-medium">Prompt versions</label>
                    <p className="text-secondary text-xs">
                        Pick the versions to compare. The first version is the control variant. The metric template is
                        applied to events tagged with this prompt name.
                    </p>
                    <div className="flex flex-col gap-3">
                        {versionSlots.map((value, index) => {
                            const disabled = disabledVersionsByIndex[index] ?? new Set<number>()
                            const options = promptVersions.map((v) => ({
                                label: `v${v.version}${v.is_latest ? ' (latest)' : ''}`,
                                value: v.version,
                                disabledReason: disabled.has(v.version)
                                    ? 'Already selected for another variant'
                                    : undefined,
                            }))
                            return (
                                <div
                                    key={index}
                                    className="flex items-center gap-2"
                                    data-attr={`llma-prompt-experiment-version-row-${index}`}
                                >
                                    <span className="flex items-center min-w-0 w-20">
                                        <span
                                            className="w-2 h-2 rounded-full shrink-0"
                                            // eslint-disable-next-line react/forbid-dom-props
                                            style={{ backgroundColor: getSeriesColor(index) }}
                                        />
                                        <span className="ml-2 text-xs font-semibold truncate text-secondary">
                                            {variantLabel(index, versionSlots.length)}
                                        </span>
                                    </span>
                                    <LemonSelect<number | null>
                                        className="flex-1"
                                        value={value}
                                        placeholder="Pick a version"
                                        options={options}
                                        onChange={(v) => setVersionAt(index, v ?? null)}
                                        data-attr={`llma-prompt-experiment-version-select-${index}`}
                                    />
                                    <LemonButton
                                        icon={<IconTrash />}
                                        size="small"
                                        type="tertiary"
                                        status="danger"
                                        onClick={() => removeVersionSlot(index)}
                                        disabledReason={
                                            versionSlots.length <= 2 ? 'Need at least two variants' : undefined
                                        }
                                        data-attr={`llma-prompt-experiment-remove-variant-${index}`}
                                    />
                                </div>
                            )
                        })}
                    </div>
                    {/* Spacer matches the variant-label column width (w-20) plus the row gap (gap-2)
                        so the "Add variant" button visually aligns with the version-select column. */}
                    <div className="flex items-center gap-2">
                        <span className="w-20 shrink-0" />
                        <LemonButton
                            icon={<IconPlus />}
                            type="secondary"
                            size="xsmall"
                            onClick={addVersionSlot}
                            disabledReason={
                                versionSlots.length >= MAX_VERSIONS
                                    ? `Maximum ${MAX_VERSIONS} variants`
                                    : !canAddSlot
                                      ? 'Fill all variants before adding more'
                                      : undefined
                            }
                            data-attr="llma-prompt-experiment-add-variant"
                        >
                            Add variant
                        </LemonButton>
                    </div>
                </div>

                <div className="space-y-3">
                    <label className="text-sm font-medium">Metrics</label>
                    <p className="text-secondary text-xs">
                        Pick one or more metric templates to attach as primary metrics. Each becomes a separate metric
                        scoped to this prompt.
                    </p>
                    {templatesLoading ? (
                        <p className="text-secondary text-xs">Loading templates…</p>
                    ) : (
                        <div className="flex flex-col gap-3">
                            {templates.map((t) => {
                                const key = t.key as TemplatesEnumApi
                                return (
                                    <div
                                        key={t.key}
                                        className="flex items-start gap-2"
                                        data-attr={`llma-prompt-experiment-template-row-${t.key}`}
                                    >
                                        <LemonCheckbox
                                            checked={selectedTemplates.includes(key)}
                                            onChange={() => toggleTemplate(key)}
                                            data-attr={`llma-prompt-experiment-template-checkbox-${t.key}`}
                                            label={
                                                <span className="flex flex-col">
                                                    <span className="text-sm font-medium">{t.label}</span>
                                                    <span className="text-secondary text-xs">{t.description}</span>
                                                </span>
                                            }
                                        />
                                    </div>
                                )
                            })}
                        </div>
                    )}
                </div>
            </LemonModalContent>

            <LemonModalFooter>
                <LemonButton
                    type="secondary"
                    onClick={closeModal}
                    disabledReason={isSubmitting ? 'Creating…' : undefined}
                    data-attr="llma-prompt-experiment-cancel"
                >
                    Cancel
                </LemonButton>
                <LemonButton
                    type="primary"
                    onClick={submitCreate}
                    loading={isSubmitting}
                    disabledReason={
                        canSubmit ? undefined : 'Pick at least two distinct versions and one metric template'
                    }
                    data-attr="llma-prompt-experiment-submit"
                >
                    Create experiment
                </LemonButton>
            </LemonModalFooter>
        </LemonModal>
    )
}
