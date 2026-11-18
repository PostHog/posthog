import clsx from 'clsx'

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

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { urls } from 'scenes/urls'

import { ExperimentConclusion } from '~/types'

import { CONCLUSION_DISPLAY_CONFIG } from 'products/experiments/frontend/constants'
import { hasFrozenExposureStamps } from 'products/experiments/frontend/experimentActions'

import { getExperimentVariants } from '../utils'
import {
    CONCLUSION_COMMENT_PLACEHOLDER,
    FROZEN_EXPOSURE_NOTE,
    PauseExperimentCopy,
    ResumeExperimentCopy,
    VARIANT_TO_KEEP_HELP,
    releaseOptions,
    useConclusionForm,
    useEditConclusionModal,
    useFinishExperimentModal,
    usePauseResumeModal,
} from './experimentModalsModel'
import { QuillEditConclusionModal, QuillFinishExperimentModal, QuillPauseResumeModal } from './QuillExperimentModals'
import { VariantTag } from './VariantTag'

function useQuillModals(): boolean {
    const resultsRedesign = useFeatureFlag('EXPERIMENTS_RESULTS_REDESIGN')
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    return todayRailNav && resultsRedesign
}

function ConclusionForm(): JSX.Element {
    const { conclusion, comment, setConclusion, setComment } = useConclusionForm()

    return (
        <div className="space-y-4">
            <div>
                <LemonLabel>Conclusion</LemonLabel>
                <LemonSelect
                    className="w-full"
                    dropdownMaxContentWidth={true}
                    value={conclusion}
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
                    onChange={(value) => setConclusion(value || undefined)}
                />
            </div>
            <div>
                <LemonLabel>Comment (optional)</LemonLabel>
                <LemonTextArea
                    className="w-full border rounded p-2"
                    minRows={6}
                    maxLength={4000}
                    placeholder={CONCLUSION_COMMENT_PLACEHOLDER}
                    value={comment}
                    onChange={setComment}
                />
            </div>
        </div>
    )
}

export function EditConclusionModal(): JSX.Element {
    const { isOpen, close, cancel, save, saveDisabledReason } = useEditConclusionModal()
    const quill = useQuillModals()

    if (quill) {
        return (
            <QuillEditConclusionModal
                isOpen={isOpen}
                close={close}
                cancel={cancel}
                save={save}
                saveDisabledReason={saveDisabledReason}
            />
        )
    }

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={close}
            title="Edit conclusion"
            width={600}
            footer={
                <div className="flex items-center gap-2">
                    <LemonButton type="secondary" onClick={cancel}>
                        Cancel
                    </LemonButton>
                    <LemonButton onClick={save} type="primary" disabledReason={saveDisabledReason}>
                        Save
                    </LemonButton>
                </div>
            }
        >
            <ConclusionForm />
        </LemonModal>
    )
}

function PauseResumeModal({ kind }: { kind: 'pause' | 'resume' }): JSX.Element {
    const { isOpen, close, confirm, confirmDisabledReason } = usePauseResumeModal(kind)
    const quill = useQuillModals()
    const title = kind === 'pause' ? 'Pause experiment' : 'Resume experiment'

    if (quill) {
        return (
            <QuillPauseResumeModal
                kind={kind}
                isOpen={isOpen}
                close={close}
                confirm={confirm}
                confirmDisabledReason={confirmDisabledReason}
            />
        )
    }

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={close}
            title={title}
            width={600}
            footer={
                <div className="flex items-center gap-2">
                    <LemonButton type="secondary" onClick={close}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        onClick={confirm}
                        type="primary"
                        status={kind === 'pause' ? 'danger' : undefined}
                        disabledReason={confirmDisabledReason}
                    >
                        {title}
                    </LemonButton>
                </div>
            }
        >
            <div className="space-y-4">{kind === 'pause' ? <PauseExperimentCopy /> : <ResumeExperimentCopy />}</div>
        </LemonModal>
    )
}

export function PauseExperimentModal(): JSX.Element {
    return <PauseResumeModal kind="pause" />
}

export function ResumeExperimentModal(): JSX.Element {
    return <PauseResumeModal kind="resume" />
}

export function FinishExperimentModal(): JSX.Element {
    const model = useFinishExperimentModal()
    const quill = useQuillModals()

    if (quill) {
        return <QuillFinishExperimentModal model={model} />
    }

    const {
        experiment,
        isOpen: isFinishExperimentModalOpen,
        isSingleVariantShipped,
        shippedVariantKey,
        endExperimentLoading,
        aggregationTargetName,
        selectedVariantKey,
        setSelectedVariantKey,
        releaseToEveryone,
        setReleaseToEveryone,
        openCleanupPr,
        setOpenCleanupPr,
        cleanupRepository,
        setCleanupRepository,
        setAsTeamDefault,
        setSetAsTeamDefault,
        cleanupTarget,
        cleanupPrAvailable,
        cleanupNeedsRepositoryPick,
        teamDefaultRestrictionReason,
        handleClose,
        handleEndExperiment,
        endDisabledReason,
    } = model

    const releaseModeOptions = releaseOptions(aggregationTargetName).map((option) => ({
        ...option,
        icon: option.value ? <IconGlobe className="text-lg" /> : <IconList className="text-lg" />,
    }))

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
                            disabledReason={endDisabledReason}
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
                                <LemonBanner type="info">{FROZEN_EXPOSURE_NOTE}</LemonBanner>
                            )}
                            <div>
                                <LemonLabel showOptional>Variant to keep</LemonLabel>
                                <div className="text-xs text-muted mb-1">{VARIANT_TO_KEEP_HELP}</div>
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
                                        {releaseModeOptions.map((option) => {
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
