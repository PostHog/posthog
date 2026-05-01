import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { LemonInput, LemonModal, LemonSelect } from '@posthog/lemon-ui'

import api from 'lib/api'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { PaginationManual } from 'lib/lemon-ui/PaginationControl'
import { toParams } from 'lib/utils'
import { experimentsLogic } from 'scenes/experiments/experimentsLogic'
import { slugifyFeatureFlagKey } from 'scenes/feature-flags/featureFlagLogic'
import { FLAGS_PER_PAGE, FeatureFlagsFilters } from 'scenes/feature-flags/featureFlagsLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { teamLogic } from 'scenes/teamLogic'

import { Experiment, FeatureFlagType } from '~/types'

import { ExperimentFlagKeyInput } from './ExperimentFlagKeyInput'

interface CopyExperimentToProjectModalProps {
    isOpen: boolean
    onClose: () => void
    experiment: Experiment
}

const DEFAULT_FILTERS: Partial<FeatureFlagsFilters> = { search: undefined, order: undefined, page: 1 }

export function CopyExperimentToProjectModal({
    isOpen,
    onClose,
    experiment,
}: CopyExperimentToProjectModalProps): JSX.Element {
    const { copyExperimentToProject } = useActions(experimentsLogic)
    const { experimentsLoading } = useValues(experimentsLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { currentTeam } = useValues(teamLogic)

    const teamOptions =
        currentOrganization?.teams
            ?.filter((team) => team.id !== currentTeam?.id)
            .map((team) => ({ value: team.id, label: team.name }))
            .sort((a, b) => a.label.localeCompare(b.label)) || []
    const onlyTeamOptionValue = teamOptions.length === 1 ? teamOptions[0].value : null

    const [selectedTeamId, setSelectedTeamId] = useState<number | null>(null)
    const [experimentName, setExperimentName] = useState('')
    const [flagKey, setFlagKey] = useState('')
    const [flagKeyManuallyEdited, setFlagKeyManuallyEdited] = useState(false)
    const [isExistingFlag, setIsExistingFlag] = useState(false)
    const [showReuseFlag, setShowReuseFlag] = useState(false)

    // Local state for target project's feature flags
    const [targetFeatureFlags, setTargetFeatureFlags] = useState<{ results: FeatureFlagType[]; count: number }>({
        results: [],
        count: 0,
    })
    const [targetFlagsLoading, setTargetFlagsLoading] = useState(false)
    const [targetFlagFilters, setTargetFlagFilters] = useState<Partial<FeatureFlagsFilters>>(DEFAULT_FILTERS)
    const selectedTeam = currentOrganization?.teams?.find((team) => team.id === selectedTeamId)

    useEffect(() => {
        if (isOpen && onlyTeamOptionValue !== null && selectedTeamId === null) {
            handleTeamChange(onlyTeamOptionValue)
        }
    }, [isOpen, onlyTeamOptionValue, selectedTeamId])

    const fetchTargetFlags = async (projectId: number, filters: Partial<FeatureFlagsFilters>): Promise<void> => {
        setTargetFlagsLoading(true)
        try {
            const params = {
                ...filters,
                limit: FLAGS_PER_PAGE,
                offset: filters.page ? (filters.page - 1) * FLAGS_PER_PAGE : 0,
            }
            const data = await api.get(
                `api/projects/${projectId}/experiments/eligible_feature_flags/?${toParams(params)}`
            )
            setTargetFeatureFlags(data)
        } finally {
            setTargetFlagsLoading(false)
        }
    }

    useEffect(() => {
        if (selectedTeam?.project_id) {
            void fetchTargetFlags(selectedTeam.project_id, targetFlagFilters)
        }
    }, [selectedTeam?.project_id, targetFlagFilters])

    const handleTeamChange = (id: number | null): void => {
        setSelectedTeamId(id)
        // Reset flag state when switching projects
        setFlagKey('')
        setFlagKeyManuallyEdited(false)
        setIsExistingFlag(false)
        setShowReuseFlag(false)
        setTargetFlagFilters(DEFAULT_FILTERS)
    }

    const handleNameChange = (value: string): void => {
        setExperimentName(value)
        if (!flagKeyManuallyEdited) {
            setFlagKey(slugifyFeatureFlagKey(value, { fromTitleInput: true }))
            setIsExistingFlag(false)
        }
    }

    const handleFlagKeyChange = (value: string): void => {
        setFlagKeyManuallyEdited(true)
        setIsExistingFlag(false)
        setFlagKey(slugifyFeatureFlagKey(value))
    }

    const selectExistingFlag = (key: string): void => {
        setFlagKeyManuallyEdited(true)
        setIsExistingFlag(true)
        setFlagKey(key)
    }

    const handleCopy = (): void => {
        if (selectedTeamId && selectedTeam) {
            copyExperimentToProject({
                id: experiment.id as number,
                targetProjectId: selectedTeam.project_id,
                targetTeamId: selectedTeamId,
                featureFlagKey: flagKey || undefined,
                name: experimentName.trim() || undefined,
                onSuccess: handleClose,
            })
        }
    }

    const handleClose = (): void => {
        setSelectedTeamId(null)
        setExperimentName('')
        setFlagKey('')
        setFlagKeyManuallyEdited(false)
        setIsExistingFlag(false)
        setShowReuseFlag(false)
        setTargetFlagFilters(DEFAULT_FILTERS)
        setTargetFeatureFlags({ results: [], count: 0 })
        onClose()
    }

    const handleTargetFlagFiltersChange = (filters: Partial<FeatureFlagsFilters>): void => {
        setTargetFlagFilters((prev) => ({ ...prev, ...filters }))
    }

    const currentPage = targetFlagFilters.page || 1
    const hasNextPage = targetFeatureFlags.count > currentPage * FLAGS_PER_PAGE
    const hasPreviousPage = currentPage > 1
    const needsPagination = targetFeatureFlags.count > FLAGS_PER_PAGE

    const targetFlagPagination: PaginationManual = {
        controlled: true,
        pageSize: FLAGS_PER_PAGE,
        currentPage,
        entryCount: targetFeatureFlags.count,
        onForward:
            needsPagination && hasNextPage
                ? () => setTargetFlagFilters((prev) => ({ ...prev, page: (prev.page || 1) + 1 }))
                : undefined,
        onBackward:
            needsPagination && hasPreviousPage
                ? () => setTargetFlagFilters((prev) => ({ ...prev, page: Math.max(1, (prev.page || 1) - 1) }))
                : undefined,
    }

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={handleClose}
            title="Copy experiment to project"
            width="max-content"
            footer={
                <div className="flex justify-end">
                    <LemonButton
                        type="primary"
                        disabledReason={!selectedTeamId ? 'Select a project' : undefined}
                        onClick={handleCopy}
                        loading={experimentsLoading}
                    >
                        Copy
                    </LemonButton>
                </div>
            }
        >
            <div className="space-y-4">
                <div className="text-muted max-w-xl">
                    The experiment and its feature flag will be copied as a draft. The feature flag will be disabled by
                    default in the target project. If a feature flag with the same key already exists, or you select an
                    existing flag, the release configuration for that flag will not be changed.
                </div>

                <div>
                    <div className="font-semibold mb-2">Destination project</div>
                    <LemonSelect
                        placeholder="Select a project"
                        fullWidth
                        dropdownMatchSelectWidth={false}
                        value={selectedTeamId}
                        onChange={handleTeamChange}
                        options={teamOptions}
                    />
                </div>

                {selectedTeamId && (
                    <>
                        <div>
                            <label className="font-semibold mb-1 block">Experiment name</label>
                            <LemonInput
                                value={experimentName}
                                onChange={handleNameChange}
                                placeholder={`${experiment.name} (Copy)`}
                                data-attr="copy-experiment-name"
                            />
                        </div>

                        <ExperimentFlagKeyInput
                            flagKey={flagKey}
                            onFlagKeyChange={handleFlagKeyChange}
                            isExistingFlag={isExistingFlag}
                            sourceExperiment={experiment}
                            featureFlags={targetFeatureFlags}
                            featureFlagsLoading={targetFlagsLoading}
                            featureFlagFilters={targetFlagFilters}
                            onFeatureFlagFiltersChange={handleTargetFlagFiltersChange}
                            featureFlagPagination={targetFlagPagination}
                            onSelectExistingFlag={selectExistingFlag}
                            showReuseFlag={showReuseFlag}
                            onToggleReuseFlag={setShowReuseFlag}
                        />
                    </>
                )}
            </div>
        </LemonModal>
    )
}
