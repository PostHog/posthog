import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { FEATURE_FLAGS, OrganizationMembershipLevel } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { groupsModel } from '~/models/groupsModel'
import { Experiment, ExperimentConclusion } from '~/types'

import type { ExperimentFlagCleanupTargetApi } from 'products/experiments/frontend/generated/api.schemas'

import { experimentLogic } from '../experimentLogic'
import { modalsLogic } from '../modalsLogic'
import { flagCleanupTargetLogic } from './flagCleanupTargetLogic'

export const CONCLUSION_COMMENT_PLACEHOLDER = 'Optional details about why this conclusion was selected...'
export const FROZEN_EXPOSURE_NOTE =
    'Exposure is frozen for this experiment. If you end it without shipping a variant, the feature flag keeps serving variants only to the frozen snapshot of already-enrolled users. Shipping a variant removes the freeze.'
export const VARIANT_TO_KEEP_HELP = 'Leave blank to end the experiment without rolling out a variant.'

export function PauseExperimentCopy(): JSX.Element {
    return (
        <>
            <div>
                Pausing the experiment will <b>disable the feature flag</b>, preventing any users from seeing the
                experiment variants. This is useful when you need to quickly stop exposing users to the experiment.
            </div>
            <div>The experiment can be resumed at any time. All collected data will be preserved.</div>
        </>
    )
}

export function ResumeExperimentCopy(): JSX.Element {
    return (
        <>
            <div>
                Resuming the experiment will <b>enable the feature flag</b>, allowing users to see the experiment
                variants again. This will continue the experiment from where it was paused.
            </div>
            <div>All previously collected data is preserved and new events will be tracked.</div>
        </>
    )
}

export function useConclusionForm(): {
    conclusion: ExperimentConclusion | undefined
    comment: string
    setConclusion: (conclusion: ExperimentConclusion | undefined) => void
    setComment: (comment: string) => void
} {
    const { experiment } = useValues(experimentLogic)
    const { setExperiment } = useActions(experimentLogic)
    return {
        conclusion: experiment.conclusion ?? undefined,
        comment: experiment.conclusion_comment || '',
        setConclusion: (conclusion) => setExperiment({ conclusion }),
        setComment: (comment) => setExperiment({ conclusion_comment: comment }),
    }
}

export function useEditConclusionModal(): {
    isOpen: boolean
    close: () => void
    cancel: () => void
    save: () => void
    saveDisabledReason?: string
} {
    const { experiment } = useValues(experimentLogic)
    const { updateExperiment, restoreUnmodifiedExperiment } = useActions(experimentLogic)
    const { closeEditConclusionModal } = useActions(modalsLogic)
    const { isEditConclusionModalOpen } = useValues(modalsLogic)

    return {
        isOpen: isEditConclusionModalOpen,
        close: closeEditConclusionModal,
        cancel: () => {
            restoreUnmodifiedExperiment()
            closeEditConclusionModal()
        },
        save: () => {
            updateExperiment({
                conclusion: experiment.conclusion,
                conclusion_comment: experiment.conclusion_comment,
            })
            closeEditConclusionModal()
        },
        saveDisabledReason: !experiment.conclusion ? 'Select a conclusion' : undefined,
    }
}

export function usePauseResumeModal(kind: 'pause' | 'resume'): {
    isOpen: boolean
    close: () => void
    confirm: () => void
    confirmDisabledReason?: string
} {
    const { experiment } = useValues(experimentLogic)
    const { pauseExperiment, resumeExperiment } = useActions(experimentLogic)
    const { closePauseExperimentModal, closeResumeExperimentModal } = useActions(modalsLogic)
    const { isPauseExperimentModalOpen, isResumeExperimentModalOpen } = useValues(modalsLogic)

    return {
        isOpen: kind === 'pause' ? isPauseExperimentModalOpen : isResumeExperimentModalOpen,
        close: kind === 'pause' ? closePauseExperimentModal : closeResumeExperimentModal,
        confirm: () => (kind === 'pause' ? pauseExperiment() : resumeExperiment()),
        confirmDisabledReason: !experiment.feature_flag ? 'No feature flag linked' : undefined,
    }
}

export interface ReleaseOption {
    value: boolean
    label: string
    recommended: boolean
    description: string
}

export function releaseOptions(aggregationTargetName: string): ReleaseOption[] {
    return [
        {
            value: false,
            label: 'Roll out to the experiment population',
            recommended: true,
            description: `Only ${aggregationTargetName} already in the experiment see the variant. Per-user variant overrides still apply.`,
        },
        {
            value: true,
            label: `Roll out to all ${aggregationTargetName}`,
            recommended: false,
            description: `All ${aggregationTargetName} see the variant, including those outside the experiment. Per-user variant overrides are bypassed.`,
        },
    ]
}

export interface FinishExperimentModalModel {
    experiment: Experiment
    isOpen: boolean
    isSingleVariantShipped: boolean
    shippedVariantKey: string | null
    endExperimentLoading: boolean
    aggregationTargetName: string
    selectedVariantKey: string | null | undefined
    setSelectedVariantKey: (key: string | null | undefined) => void
    releaseToEveryone: boolean
    setReleaseToEveryone: (value: boolean) => void
    openCleanupPr: boolean
    setOpenCleanupPr: (value: boolean) => void
    cleanupRepository: string | null
    setCleanupRepository: (value: string | null) => void
    setAsTeamDefault: boolean
    setSetAsTeamDefault: (value: boolean) => void
    cleanupTarget: ExperimentFlagCleanupTargetApi | null
    cleanupPrAvailable: boolean
    cleanupNeedsRepositoryPick: boolean
    teamDefaultRestrictionReason: string | null
    handleClose: () => void
    handleEndExperiment: () => void
    endDisabledReason?: string
}

export function useFinishExperimentModal(): FinishExperimentModalModel {
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

    // The cleanup PR runs as a PostHog Desktop task, so the user needs Code access.
    const cleanupPrAvailable = !!featureFlags[FEATURE_FLAGS.TASKS]
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
        experiment.feature_flag?.filters?.aggregation_group_type_index != null
            ? aggregationLabel(experiment.feature_flag.filters.aggregation_group_type_index).plural
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

    const endDisabledReason =
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
            'Select a repository for the cleanup PR') ||
        undefined

    return {
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
    }
}
