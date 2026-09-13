import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconCheckCircle, IconGlobe, IconList } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonCheckbox,
    LemonInputSelect,
    LemonLabel,
    LemonModal,
    LemonSelect,
    LemonTextArea,
    Link,
} from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { FEATURE_FLAGS, OrganizationMembershipLevel } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { groupsModel } from '~/models/groupsModel'
import { ExperimentConclusion } from '~/types'

import { CONCLUSION_DISPLAY_CONFIG } from 'products/experiments/frontend/constants'
import { hasFrozenExposureStamps } from 'products/experiments/frontend/experimentActions'

import { experimentLogic } from '../experimentLogic'
import { modalsLogic } from '../modalsLogic'
import { getExperimentVariants } from '../utils'
import { flagCleanupTargetLogic } from './flagCleanupTargetLogic'
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

    const [selectedVariantKey, setSelectedVariantKey] = useState<string | null>()
    const [releaseToEveryone, setReleaseToEveryone] = useState<boolean>(false)
    const [openCleanupPr, setOpenCleanupPr] = useState<boolean>(false)
    const [cleanupRepository, setCleanupRepository] = useState<string | null>(null)
    const [setAsTeamDefault, setSetAsTeamDefault] = useState<boolean>(false)

    // Reset on open, not only on close: a failed end/ship closes the modal through the logic
    // without this component's close handler, which would leave a stale pick for the next open.
    useEffect(() => {
        if (isFinishExperimentModalOpen) {
            setOpenCleanupPr(false)
            setCleanupRepository(null)
            setSetAsTeamDefault(false)
        }
    }, [isFinishExperimentModalOpen])

    const { cleanupTarget } = useValues(flagCleanupTargetLogic({ experimentId: experiment.id as number }))

    // The cleanup PR runs as a PostHog Desktop task, so the user needs Code access on top of the rollout flag.
    const cleanupPrAvailable =
        !!featureFlags[FEATURE_FLAGS.EXPERIMENT_FLAG_CLEANUP_PR] && !!featureFlags[FEATURE_FLAGS.TASKS]
    // With several connected repositories and none saved on the experiment, the backend would
    // skip the cleanup rather than guess — so a pick is required here.
    const cleanupNeedsRepositoryPick = cleanupTarget?.source === 'ambiguous'
    // The team default is environment-wide configuration, so offering to set it follows the
    // same admin bar as the experiments_config settings endpoint.
    const teamDefaultRestrictionReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
    })

    const aggregationTargetName =
        experiment.filters.aggregation_group_type_index != null
            ? aggregationLabel(experiment.filters.aggregation_group_type_index).plural
            : 'users'

    const handleClose = (): void => {
        setOpenCleanupPr(false)
        setCleanupRepository(null)
        setSetAsTeamDefault(false)
        restoreUnmodifiedExperiment()
        closeFinishExperimentModal()
    }

    const handleEndExperiment = (): void => {
        const withCleanupPr = cleanupPrAvailable && openCleanupPr
        const repository = withCleanupPr && cleanupNeedsRepositoryPick ? cleanupRepository : null
        const repositoryAsTeamDefault = !!repository && setAsTeamDefault && !teamDefaultRestrictionReason
        if (isSingleVariantShipped || !selectedVariantKey) {
            endExperimentWithoutShipping(withCleanupPr, repository, repositoryAsTeamDefault)
        } else {
            finishExperiment({
                selectedVariantKey,
                releaseToEveryone,
                openCleanupPr: withCleanupPr,
                repository,
                setRepositoryAsTeamDefault: repositoryAsTeamDefault,
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
                            disabledReason={
                                (!experiment.conclusion && 'Select a conclusion') ||
                                // Until the target loads we don't know whether a pick is needed, and
                                // ending now would silently skip the requested cleanup PR.
                                (cleanupPrAvailable &&
                                    openCleanupPr &&
                                    !cleanupTarget &&
                                    'Checking which repository the cleanup PR would target') ||
                                (cleanupPrAvailable &&
                                    openCleanupPr &&
                                    cleanupNeedsRepositoryPick &&
                                    !cleanupRepository &&
                                    'Select a repository for the cleanup PR')
                            }
                        >
                            End experiment
                        </LemonButton>
                    </div>
                }
            >
                <div className="space-y-4">
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
                            {hasFrozenExposureStamps(experiment) && (
                                <LemonBanner type="info">
                                    Exposure is frozen for this experiment. If you end it without shipping a variant,
                                    the feature flag keeps serving variants only to the frozen snapshot of
                                    already-enrolled users. Shipping a variant removes the freeze.
                                </LemonBanner>
                            )}
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
                                        options={getExperimentVariants(experiment).map(({ key }) => ({
                                            value: key,
                                            label: (
                                                <div className="deprecated-space-x-2 inline-flex">
                                                    <VariantTag variantKey={key} />
                                                </div>
                                            ),
                                        }))}
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
                    <ConclusionForm />
                    {cleanupPrAvailable && (
                        <div className="space-y-2">
                            <LemonCheckbox
                                checked={openCleanupPr}
                                onChange={setOpenCleanupPr}
                                data-attr="experiment-open-cleanup-pr"
                                disabledReason={
                                    cleanupTarget?.source === 'no_integration' &&
                                    'Connect GitHub in your project settings to open cleanup PRs'
                                }
                                label={
                                    <span>
                                        Open a draft PR removing <code>{experiment.feature_flag?.key}</code> from your
                                        code
                                    </span>
                                }
                            />
                            {openCleanupPr && cleanupTarget?.repository && (
                                <div className="text-xs text-muted">
                                    The PR will be opened in <code>{cleanupTarget.repository}</code>.
                                </div>
                            )}
                            {openCleanupPr && cleanupNeedsRepositoryPick && (
                                <>
                                    <LemonInputSelect
                                        mode="single"
                                        value={cleanupRepository ? [cleanupRepository] : []}
                                        onChange={(repositories) => setCleanupRepository(repositories[0] ?? null)}
                                        options={(cleanupTarget?.candidates ?? []).map((repository) => ({
                                            key: repository,
                                            label: repository,
                                        }))}
                                        placeholder="Select a repository"
                                        data-attr="experiment-cleanup-repository"
                                    />
                                    {!teamDefaultRestrictionReason && (
                                        <LemonCheckbox
                                            checked={setAsTeamDefault}
                                            onChange={setSetAsTeamDefault}
                                            data-attr="experiment-cleanup-repository-team-default"
                                            label="Use this repository for all experiments in this project"
                                        />
                                    )}
                                </>
                            )}
                        </div>
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
