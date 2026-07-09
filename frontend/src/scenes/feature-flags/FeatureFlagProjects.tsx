import { useActions, useValues } from 'kea'

import { IconArrowRight } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonCheckbox, LemonDialog, LemonSelect, LemonTag } from '@posthog/lemon-ui'

import { OrganizationMembershipLevel } from 'lib/constants'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { IconSync } from 'lib/lemon-ui/icons'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { createdAtColumn, createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { cohortsModel } from '~/models/cohortsModel'
import { type Noun, groupsModel } from '~/models/groupsModel'
import { OrganizationFeatureFlag, OrganizationType } from '~/types'

import { organizationLogic } from '../organizationLogic'
import { featureFlagLogic, hasDirectFlagDependency, hasStaticCohortDependency } from './featureFlagLogic'
import { groupFilters } from './FeatureFlags'
import { FlagActiveToggleTag } from './FlagActiveToggleTag'
import { confirmFlagActiveToggleInProject, flagToggleKey } from './updateFlagActiveInProject'

const getColumns = ({
    aggregationLabel,
    currentTeamId,
    currentOrganization,
    projectFlagsToggling,
    onToggleFlagActive,
}: {
    aggregationLabel: (groupTypeIndex: number | null | undefined, deferToUserWording?: boolean) => Noun
    currentTeamId: number | null
    currentOrganization: OrganizationType | null
    projectFlagsToggling: Record<string, boolean>
    onToggleFlagActive: (record: OrganizationFeatureFlag, active: boolean) => void
}): LemonTableColumns<OrganizationFeatureFlag> => {
    return [
        {
            title: 'Project',
            dataIndex: 'team_id',
            width: '45%',
            render: (dataValue, record) => {
                const team = currentOrganization?.teams?.find((t) => t.id === Number(dataValue))
                if (!team) {
                    return '(project does not exist)'
                }
                const isCurrentTeam = team.id === currentTeamId
                const linkText = isCurrentTeam ? `${team.name} (current)` : team.name

                return (
                    <LemonTableLink
                        to={
                            !isCurrentTeam
                                ? urls.project(team.id, record.flag_id ? urls.featureFlag(record.flag_id) : '')
                                : undefined
                        }
                        title={linkText}
                    />
                )
            },
        },
        createdByColumn() as LemonTableColumn<OrganizationFeatureFlag, keyof OrganizationFeatureFlag | undefined>,
        createdAtColumn() as LemonTableColumn<OrganizationFeatureFlag, keyof OrganizationFeatureFlag | undefined>,
        {
            title: 'Release conditions',
            width: 200,
            render: function Render(_, record: OrganizationFeatureFlag) {
                const releaseText = groupFilters(record.filters, undefined, aggregationLabel)
                return typeof releaseText === 'string' && releaseText.startsWith('100% of') ? (
                    <LemonTag type="highlight">{releaseText}</LemonTag>
                ) : (
                    releaseText
                )
            },
        },
        {
            title: 'Status',
            dataIndex: 'active',
            render: (_, record) => {
                const canToggle = record.team_id !== null && record.flag_id !== null
                const toggling =
                    record.team_id !== null &&
                    record.flag_id !== null &&
                    !!projectFlagsToggling[flagToggleKey(record.team_id, record.flag_id)]
                return (
                    <FlagActiveToggleTag
                        active={record.active}
                        toggling={toggling}
                        onToggle={canToggle ? (active) => onToggleFlagActive(record, active) : undefined}
                        data-attr="feature-flag-projects-toggle"
                    />
                )
            },
        },
    ]
}

function InfoBanner(): JSX.Element {
    const { currentOrganization } = useValues(organizationLogic)
    const { featureFlag } = useValues(featureFlagLogic)
    const hasMultipleProjects = (currentOrganization?.teams?.length ?? 0) > 1

    const isMember =
        !currentOrganization?.membership_level ||
        currentOrganization.membership_level < OrganizationMembershipLevel.Admin

    let text

    if (isMember && !hasMultipleProjects) {
        text = `You currently have access to only one project. If your organization manages multiple projects and you wish to copy this feature flag across them, request project access from your administrator.`
    } else if (!hasMultipleProjects) {
        text = `This feature enables the copying of a feature flag across different projects. Once additional projects are added within your organization, you'll be able to replicate this flag to them.`
    } else if (!featureFlag.can_edit) {
        text = `You don't have the necessary permissions to copy this flag to another project. Contact your administrator to request editing rights.`
    } else {
        return <></>
    }

    return (
        <LemonBanner type="info" className="mb-4">
            {text}
        </LemonBanner>
    )
}

function FeatureFlagCopySection(): JSX.Element {
    const {
        featureFlag,
        copyDestinationProject,
        copyDependencies,
        copyDependencyRequirements,
        copyDependencyRequirementsLoading,
        projectsWithCurrentFlag,
        featureFlagCopyLoading,
        copySchedule,
        disableCopiedFlag,
        scheduledChanges,
    } = useValues(featureFlagLogic)
    const { copyFlag, setCopyDependencies, setCopyDestinationProject, setCopySchedule, setDisableCopiedFlag } =
        useActions(featureFlagLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { currentTeam } = useValues(teamLogic)
    const { allCohorts } = useValues(cohortsModel)

    const hasStaticCohort = hasStaticCohortDependency(featureFlag, allCohorts.results)
    const hasMultipleProjects = (currentOrganization?.teams?.length ?? 0) > 1
    const hasFlagDependency = hasDirectFlagDependency(featureFlag)
    const copiedDependencyCount = copyDependencyRequirements?.copied_dependency_keys.length ?? 0
    const copiedDependencyLabel = copiedDependencyCount === 1 ? 'dependency' : 'dependencies'
    const dependencyActionLabel =
        copyDependencyRequirementsLoading || !copyDependencyRequirements
            ? 'Checking'
            : copyDependencyRequirements.can_copy_dependencies
              ? `${copiedDependencyCount} missing`
              : copyDependencyRequirements.warnings.length > 0
                ? 'Unavailable'
                : 'Already satisfied'
    const dependencyDisabledReason =
        copyDependencyRequirementsLoading || !copyDependencyRequirements
            ? 'Checking dependency availability'
            : !copyDependencyRequirements.can_copy_dependencies
              ? copyDependencyRequirements.reason
              : undefined
    const copyLoading = featureFlagCopyLoading || (copyDependencies && copyDependencyRequirementsLoading)

    const openCopyDependenciesDialog = (): void => {
        if (!copyDependencyRequirements?.can_copy_dependencies) {
            return
        }

        LemonDialog.open({
            title: 'Copy dependencies?',
            description: (
                <>
                    <p>
                        Include {copiedDependencyCount} missing {copiedDependencyLabel} when this flag is copied to the
                        destination project.
                    </p>
                    <p>Copied dependencies keep their current active state.</p>
                    <ul className="ml-4 list-disc max-h-60 overflow-y-auto pr-2">
                        {copyDependencyRequirements.copied_dependency_keys.map((key) => (
                            <li key={key} className="break-all">
                                {key}
                            </li>
                        ))}
                    </ul>
                    {copyDependencyRequirements.reused_dependency_keys.length > 0 && (
                        <p>
                            Existing active dependencies in the destination project will be reused and left unchanged.
                        </p>
                    )}
                    {copyDependencyRequirements.warnings.length > 0 && (
                        <LemonBanner type="warning">
                            <div className="space-y-1">
                                {copyDependencyRequirements.warnings.map((warning) => (
                                    <div key={warning}>{warning}</div>
                                ))}
                            </div>
                        </LemonBanner>
                    )}
                </>
            ),
            primaryButton: {
                children: 'Include dependencies',
                onClick: () => setCopyDependencies(true),
            },
            secondaryButton: {
                children: 'Cancel',
            },
        })
    }

    return hasMultipleProjects && featureFlag.can_edit ? (
        <>
            <h3 className="l3">Feature flag copy</h3>
            <div>Copy your flag and its configuration to another project.</div>
            {hasStaticCohort && (
                <LemonBanner type="info" className="mt-4">
                    The flag you are about to copy references a static cohort. If the cohort with identical name does
                    not exist in the target project, it will be copied as an empty cohort. This is because the
                    associated persons might not exist in the target project.
                </LemonBanner>
            )}
            <div className="flex flex-wrap items-start gap-x-4 gap-y-3 my-6">
                <div className="min-w-0 max-w-full">
                    <div className="font-semibold leading-6 h-6">Key</div>
                    <div className="border px-3 rounded h-10 text-center flex items-center justify-center max-w-200">
                        <span className="font-semibold truncate">{featureFlag.key}</span>
                    </div>
                </div>
                <div className="shrink-0">
                    <div className="h-6" />
                    <IconArrowRight className="h-10" fontSize="30" />
                </div>
                <div className="min-w-[10rem] shrink-0">
                    <div className="font-semibold leading-6 h-6">Destination project</div>
                    <LemonSelect
                        dropdownMatchSelectWidth={false}
                        value={copyDestinationProject}
                        onChange={(id) => setCopyDestinationProject(id)}
                        options={
                            currentOrganization?.teams
                                ?.map((team) => ({ value: team.id, label: team.name }))
                                .sort((a, b) => a.label.localeCompare(b.label))
                                .filter((option) => option.value !== currentTeam?.id) || []
                        }
                        className="min-w-[10rem]"
                    />
                </div>
                <div className="min-w-[9.5rem] shrink-0">
                    <div className="font-semibold leading-6 h-6">Copy schedules</div>
                    <LemonCheckbox
                        checked={copySchedule}
                        onChange={setCopySchedule}
                        disabled={scheduledChanges.length === 0}
                        label={scheduledChanges.length > 0 ? `${scheduledChanges.length} pending` : 'None available'}
                        className="h-10 flex items-center"
                    />
                </div>
                {hasFlagDependency && copyDestinationProject && (
                    <div className="min-w-[10rem] shrink-0">
                        <div className="font-semibold leading-6 h-6">Copy dependencies</div>
                        <LemonCheckbox
                            checked={copyDependencies}
                            onChange={(checked) =>
                                checked ? openCopyDependenciesDialog() : setCopyDependencies(false)
                            }
                            disabledReason={dependencyDisabledReason}
                            label={dependencyActionLabel}
                            className="h-10 flex items-center"
                        />
                    </div>
                )}
                <div className="min-w-[10rem] shrink-0">
                    <div className="font-semibold leading-6 h-6">Disable copied flag</div>
                    <LemonCheckbox
                        checked={disableCopiedFlag}
                        onChange={setDisableCopiedFlag}
                        label="Copy as disabled"
                        className="h-10 flex items-center"
                    />
                </div>
                <div className="shrink-0">
                    <div className="h-6" />
                    <LemonButton
                        disabledReason={!copyDestinationProject && 'Select destination project'}
                        loading={copyLoading}
                        type="primary"
                        icon={<IconSync />}
                        onClick={() => copyFlag()}
                        className="w-28 max-w-28"
                    >
                        {projectsWithCurrentFlag.find((p) => Number(p.team_id) === copyDestinationProject)
                            ? 'Update'
                            : 'Copy'}
                    </LemonButton>
                </div>
            </div>
        </>
    ) : (
        <></>
    )
}

export default function FeatureFlagProjects(): JSX.Element {
    const { projectsWithCurrentFlag, featureFlag, projectFlagsToggling } = useValues(featureFlagLogic)
    const { loadProjectsWithCurrentFlag, loadScheduledChanges, toggleProjectFlagActive } = useActions(featureFlagLogic)
    const { currentTeamId } = useValues(teamLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { aggregationLabel } = useValues(groupsModel)

    useOnMountEffect(() => {
        loadProjectsWithCurrentFlag()
        if (featureFlag.id) {
            loadScheduledChanges()
        }
    })

    const onToggleFlagActive = (record: OrganizationFeatureFlag, active: boolean): void => {
        if (record.team_id === null || record.flag_id === null) {
            return
        }
        const teamId = record.team_id
        const flagId = record.flag_id
        confirmFlagActiveToggleInProject({
            teamName: currentOrganization?.teams?.find((t) => t.id === teamId)?.name ?? `Project ${teamId}`,
            active,
            onConfirm: () => toggleProjectFlagActive(teamId, flagId, active),
        })
    }

    return (
        <div>
            <InfoBanner />
            <FeatureFlagCopySection />
            <LemonTable
                loading={false}
                dataSource={projectsWithCurrentFlag}
                columns={getColumns({
                    currentTeamId,
                    currentOrganization,
                    aggregationLabel,
                    projectFlagsToggling,
                    onToggleFlagActive,
                })}
                emptyState="This feature flag is not being used in any other project."
            />
        </div>
    )
}
