import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconCheckCircle, IconGlobe, IconList } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonCheckbox,
    LemonLabel,
    LemonModal,
    LemonSelect,
    LemonTextArea,
    Link,
} from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { groupsModel } from '~/models/groupsModel'
import { ExperimentConclusion } from '~/types'

import { CONCLUSION_DISPLAY_CONFIG } from '../constants'
import { experimentLogic } from '../experimentLogic'
import { modalsLogic } from '../modalsLogic'
import { VariantTag } from './VariantTag'

function ConclusionForm(): JSX.Element {
    const { experiment } = useValues(experimentLogic)
    const { setExperiment } = useActions(experimentLogic)

    return (
        <div className="space-y-4">
            <div>
                <LemonLabel>Conclusion</LemonLabel>
                <LemonSelect
                    className="w-full"
                    dropdownMaxContentWidth={true}
                    value={experiment.conclusion}
                    options={Object.values(ExperimentConclusion).map((conclusion) => ({
                        value: conclusion,
                        label: (
                            <div className="py-2 px-1">
                                <div className="font-semibold mb-1.5">
                                    <div className="font-semibold flex items-center gap-2">
                                        <div
                                            className={clsx(
                                                'w-2 h-2 rounded-full',
                                                CONCLUSION_DISPLAY_CONFIG[conclusion].color
                                            )}
                                        />
                                        <span>{CONCLUSION_DISPLAY_CONFIG[conclusion].title}</span>
                                    </div>
                                </div>
                                <div className="text-xs text-muted">
                                    {CONCLUSION_DISPLAY_CONFIG[conclusion].description}
                                </div>
                            </div>
                        ),
                    }))}
                    onChange={(value) => {
                        setExperiment({
                            conclusion: value || undefined,
                        })
                    }}
                />
            </div>
            <div>
                <LemonLabel>Comment (optional)</LemonLabel>
                <LemonTextArea
                    className="w-full border rounded p-2"
                    minRows={6}
                    maxLength={4000}
                    placeholder="Optional details about why this conclusion was selected..."
                    value={experiment.conclusion_comment || ''}
                    onChange={(value) =>
                        setExperiment({
                            conclusion_comment: value,
                        })
                    }
                />
            </div>
        </div>
    )
}

export function EditConclusionModal(): JSX.Element {
    const { experiment } = useValues(experimentLogic)
    const { updateExperiment, restoreUnmodifiedExperiment } = useActions(experimentLogic)
    const { closeEditConclusionModal } = useActions(modalsLogic)
    const { isEditConclusionModalOpen } = useValues(modalsLogic)

    return (
        <LemonModal
            isOpen={isEditConclusionModalOpen}
            onClose={closeEditConclusionModal}
            title="Edit conclusion"
            width={600}
            footer={
                <div className="flex items-center gap-2">
                    <LemonButton
                        type="secondary"
                        onClick={() => {
                            restoreUnmodifiedExperiment()
                            closeEditConclusionModal()
                        }}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        onClick={() => {
                            updateExperiment({
                                conclusion: experiment.conclusion,
                                conclusion_comment: experiment.conclusion_comment,
                            })
                            closeEditConclusionModal()
                        }}
                        type="primary"
                        disabledReason={!experiment.conclusion && 'Select a conclusion'}
                    >
                        Save
                    </LemonButton>
                </div>
            }
        >
            <ConclusionForm />
        </LemonModal>
    )
}

export function PauseExperimentModal(): JSX.Element {
    const { experiment } = useValues(experimentLogic)
    const { pauseExperiment } = useActions(experimentLogic)
    const { closePauseExperimentModal } = useActions(modalsLogic)
    const { isPauseExperimentModalOpen } = useValues(modalsLogic)

    return (
        <LemonModal
            isOpen={isPauseExperimentModalOpen}
            onClose={closePauseExperimentModal}
            title="Pause experiment"
            width={600}
            footer={
                <div className="flex items-center gap-2">
                    <LemonButton type="secondary" onClick={closePauseExperimentModal}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        onClick={() => pauseExperiment()}
                        type="primary"
                        status="danger"
                        disabledReason={!experiment.feature_flag && 'No feature flag linked'}
                    >
                        Pause experiment
                    </LemonButton>
                </div>
            }
        >
            <div className="space-y-4">
                <div>
                    Pausing the experiment will <b>disable the feature flag</b>, preventing any users from seeing the
                    experiment variants. This is useful when you need to quickly stop exposing users to the experiment.
                </div>
                <div>The experiment can be resumed at any time. All collected data will be preserved.</div>
            </div>
        </LemonModal>
    )
}

export function ResumeExperimentModal(): JSX.Element {
    const { experiment } = useValues(experimentLogic)
    const { resumeExperiment } = useActions(experimentLogic)
    const { closeResumeExperimentModal } = useActions(modalsLogic)
    const { isResumeExperimentModalOpen } = useValues(modalsLogic)

    return (
        <LemonModal
            isOpen={isResumeExperimentModalOpen}
            onClose={closeResumeExperimentModal}
            title="Resume experiment"
            width={600}
            footer={
                <div className="flex items-center gap-2">
                    <LemonButton type="secondary" onClick={closeResumeExperimentModal}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        onClick={() => resumeExperiment()}
                        type="primary"
                        disabledReason={!experiment.feature_flag && 'No feature flag linked'}
                    >
                        Resume experiment
                    </LemonButton>
                </div>
            }
        >
            <div className="space-y-4">
                <div>
                    Resuming the experiment will <b>enable the feature flag</b>, allowing users to see the experiment
                    variants again. This will continue the experiment from where it was paused.
                </div>
                <div>All previously collected data is preserved and new events will be tracked.</div>
            </div>
        </LemonModal>
    )
}

export function FinishExperimentModal(): JSX.Element {
    const { experiment, isSingleVariantShipped, shippedVariantKey, endExperimentLoading } = useValues(experimentLogic)
    const { finishExperiment, endExperimentWithoutShipping, restoreUnmodifiedExperiment } = useActions(experimentLogic)
    const { closeFinishExperimentModal } = useActions(modalsLogic)
    const { isFinishExperimentModalOpen } = useValues(modalsLogic)
    const { aggregationLabel } = useValues(groupsModel)
    const { featureFlags } = useValues(featureFlagLogic)
    const conclusionFirst = !!featureFlags[FEATURE_FLAGS.EXPERIMENTS_END_MODAL_CONCLUSION_FIRST]

    const [selectedVariantKey, setSelectedVariantKey] = useState<string | null>()
    const [releaseToEveryone, setReleaseToEveryone] = useState<boolean>(false)
    const [openCleanupPr, setOpenCleanupPr] = useState<boolean>(false)

    // The cleanup PR runs as a PostHog Code task, so the user needs Code access on top of the rollout flag.
    const cleanupPrAvailable =
        !!featureFlags[FEATURE_FLAGS.EXPERIMENT_FLAG_CLEANUP_PR] && !!featureFlags[FEATURE_FLAGS.TASKS]

    const aggregationTargetName =
        experiment.filters.aggregation_group_type_index != null
            ? aggregationLabel(experiment.filters.aggregation_group_type_index).plural
            : 'users'

    const handleClose = (): void => {
        setOpenCleanupPr(false)
        restoreUnmodifiedExperiment()
        closeFinishExperimentModal()
    }

    const handleEndExperiment = (): void => {
        const withCleanupPr = cleanupPrAvailable && openCleanupPr
        if (isSingleVariantShipped || !selectedVariantKey) {
            endExperimentWithoutShipping(withCleanupPr)
        } else {
            finishExperiment({
                selectedVariantKey,
                releaseToEveryone,
                openCleanupPr: withCleanupPr,
            })
        }
    }

    const releaseOptions = [
        {
            value: false,
            icon: <IconList className="text-lg" />,
            label: 'Roll out to the experiment population',
            recommended: true,
            description: `Only ${aggregationTargetName} already in the experiment see the variant. Per-user variant overrides still apply.`,
        },
        {
            value: true,
            icon: <IconGlobe className="text-lg" />,
            label: `Roll out to all ${aggregationTargetName}`,
            recommended: false,
            description: `All ${aggregationTargetName} see the variant, including those outside the experiment. Per-user variant overrides are bypassed.`,
        },
    ] as const

    return (
        <>
            <LemonModal
                isOpen={isFinishExperimentModalOpen}
                onClose={handleClose}
                width={600}
                title="End experiment"
                footer={
                    <div className="flex items-center gap-2">
                        <LemonButton type="secondary" onClick={handleClose}>
                            Cancel
                        </LemonButton>
                        <LemonButton
                            onClick={handleEndExperiment}
                            type="primary"
                            loading={endExperimentLoading}
                            disabledReason={!experiment.conclusion && 'Select a conclusion'}
                        >
                            End experiment
                        </LemonButton>
                    </div>
                }
            >
                <div className="space-y-4">
                    {conclusionFirst && <ConclusionForm />}
                    {isSingleVariantShipped ? (
                        <div>
                            <LemonBanner type="info" className="mb-4">
                                <b>
                                    <VariantTag variantKey={shippedVariantKey || ''} />
                                </b>{' '}
                                is already rolled out to 100% of {aggregationTargetName}. Ending this experiment will
                                mark it as complete without changing the feature flag.
                            </LemonBanner>
                        </div>
                    ) : (
                        <>
                            <div>
                                <LemonLabel showOptional>Variant to keep</LemonLabel>
                                <div className="text-xs text-muted mb-1">
                                    Leave blank to end the experiment without rolling out a variant.
                                </div>
                                <div className="w-1/2 mt-1">
                                    <LemonSelect
                                        className="w-full"
                                        data-attr="metrics-selector"
                                        value={selectedVariantKey}
                                        placeholder="Select a variant"
                                        onChange={(variantKey) => {
                                            setSelectedVariantKey(variantKey)
                                        }}
                                        allowClear={true}
                                        options={
                                            experiment.feature_flag?.filters.multivariate?.variants?.map(({ key }) => ({
                                                value: key,
                                                label: (
                                                    <div className="deprecated-space-x-2 inline-flex">
                                                        <VariantTag variantKey={key} />
                                                    </div>
                                                ),
                                            })) || []
                                        }
                                    />
                                </div>
                            </div>
                            {selectedVariantKey && (
                                <div className="flex flex-col gap-2">
                                    <LemonLabel>How to release this variant</LemonLabel>
                                    <div
                                        className="grid grid-cols-1 md:grid-cols-2 gap-3"
                                        role="radiogroup"
                                        aria-label="How to release this variant"
                                        data-attr="ship-variant-release-mode"
                                    >
                                        {releaseOptions.map((option) => {
                                            const isSelected = releaseToEveryone === option.value
                                            return (
                                                <div
                                                    key={String(option.value)}
                                                    role="radio"
                                                    aria-checked={isSelected}
                                                    tabIndex={0}
                                                    className={`rounded p-3 cursor-pointer transition-colors ${
                                                        isSelected
                                                            ? 'bg-accent-highlight-light border-2 border-accent'
                                                            : 'border bg-surface-primary border-primary hover:bg-fill-button-tertiary-hover'
                                                    }`}
                                                    onClick={() => setReleaseToEveryone(option.value)}
                                                    onKeyDown={(e) => {
                                                        if (e.key === 'Enter' || e.key === ' ') {
                                                            e.preventDefault()
                                                            setReleaseToEveryone(option.value)
                                                        }
                                                    }}
                                                    data-attr={`ship-variant-release-mode-${
                                                        option.value ? 'everyone' : 'population'
                                                    }`}
                                                >
                                                    <div className="flex flex-col gap-1">
                                                        <div className="flex items-center gap-2">
                                                            {option.icon}
                                                            <span className="font-medium flex-1">
                                                                {option.label}
                                                                {option.recommended && (
                                                                    <span className="text-secondary text-xs font-normal ml-1">
                                                                        (recommended)
                                                                    </span>
                                                                )}
                                                            </span>
                                                            {isSelected && (
                                                                <IconCheckCircle className="text-accent text-base" />
                                                            )}
                                                        </div>
                                                        <span className="text-xs text-muted">{option.description}</span>
                                                    </div>
                                                </div>
                                            )
                                        })}
                                    </div>
                                </div>
                            )}
                        </>
                    )}
                    {!conclusionFirst && <ConclusionForm />}
                    {cleanupPrAvailable && (
                        <LemonCheckbox
                            checked={openCleanupPr}
                            onChange={setOpenCleanupPr}
                            data-attr="experiment-open-cleanup-pr"
                            label={
                                <span>
                                    Open a draft PR removing <code>{experiment.feature_flag?.key}</code> from your code
                                </span>
                            }
                        />
                    )}
                    {!isSingleVariantShipped && (
                        <LemonBanner type="info" className="mb-4">
                            For more precise control over your release, adjust the rollout percentage and release
                            conditions in the{' '}
                            <Link
                                target="_blank"
                                className="font-semibold"
                                to={experiment.feature_flag ? urls.featureFlag(experiment.feature_flag.id) : undefined}
                            >
                                {experiment.feature_flag?.key}
                            </Link>{' '}
                            feature flag.
                        </LemonBanner>
                    )}
                </div>
            </LemonModal>
        </>
    )
}
