import { LemonBanner, LemonButton, LemonSelect, LemonTag, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { IconArrowRight, IconSync } from 'lib/lemon-ui/icons'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { createdAtColumn, createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { useEffect } from 'react'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { cohortsModel } from '~/models/cohortsModel'
import { groupsModel } from '~/models/groupsModel'
import { FeatureFlagType, OrganizationFeatureFlag } from '~/types'

import { organizationLogic } from '../organizationLogic'
import { featureFlagLogic } from './featureFlagLogic'
import { groupFilters } from './FeatureFlags'

function checkHasStaticCohort(featureFlag: FeatureFlagType): boolean {
    const { cohorts } = useValues(cohortsModel)
    const staticCohorts = new Set()
    cohorts.forEach((cohort) => {
        if (cohort.is_static) {
            staticCohorts.add(cohort.id)
        }
    })

    for (const group of featureFlag.filters.groups) {
        for (const prop of group.properties || []) {
            if (prop.type === 'cohort' && staticCohorts.has(prop.value)) {
                return true
            }
        }
    }
    return false
}

const getColumns = (): LemonTableColumns<OrganizationFeatureFlag> => {
    const { currentTeamId } = useValues(teamLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { updateCurrentTeam } = useActions(userLogic)
    const { aggregationLabel } = useValues(groupsModel)

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

                return isCurrentTeam ? (
                    <span className="font-semibold">{linkText}</span>
                ) : (
                    <Link
                        className="row-name"
                        onClick={() => {
                            updateCurrentTeam(team.id, `/feature_flags/${record.flag_id}`)
                        }}
                    >
                        {linkText}
                    </Link>
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
            render: (dataValue) => {
                return dataValue ? (
                    <LemonTag type="success" className="uppercase">
                        Enabled
                    </LemonTag>
                ) : (
                    <LemonTag type="default" className="uppercase">
                        Disabled
                    </LemonTag>
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
    const { featureFlag, copyDestinationProject, projectsWithCurrentFlag, featureFlagCopyLoading } =
        useValues(featureFlagLogic)
    const { setCopyDestinationProject, copyFlag } = useActions(featureFlagLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { currentTeam } = useValues(teamLogic)

    const hasStaticCohort = checkHasStaticCohort(featureFlag)
    const hasMultipleProjects = (currentOrganization?.teams?.length ?? 0) > 1

    return hasMultipleProjects && featureFlag.can_edit ? (
        <>
            <h3 className="l3">Feature flag copy</h3>
            <div className="ant-row">Copy your flag and its configuration to another project.</div>
            {hasStaticCohort && (
                <LemonBanner type="info" className="mt-4">
                    The flag you are about to copy references a static cohort. If the cohort with identical name does
                    not exist in the target project, it will be copied as an empty cohort. This is because the
                    associated persons might not exist in the target project.
                </LemonBanner>
            )}
            <div className="inline-flex gap-4 my-6">
                <div>
                    <div className="font-semibold leading-6 h-6">Key</div>
                    <div className="border px-3 rounded h-10 text-center flex items-center justify-center max-w-200">
                        <span className="font-semibold truncate">{featureFlag.key}</span>
                    </div>
                </div>
                <div>
                    <div className="h-6" />
                    <IconArrowRight className="h-10" fontSize="30" />
                </div>
                <div>
                    <div className="font-semibold leading-6 h-6">Destination project</div>
                    <LemonSelect
                        dropdownMatchSelectWidth={false}
                        value={copyDestinationProject}
                        onChange={(id) => setCopyDestinationProject(id)}
                        options={
                            currentOrganization?.teams
                                ?.map((team) => ({ value: team.id, label: team.name }))
                                .filter((option) => option.value !== currentTeam?.id) || []
                        }
                        className="min-w-40"
                    />
                </div>
                <div>
                    <div className="h-6" />
                    <LemonButton
                        disabledReason={!copyDestinationProject && 'Select destination project'}
                        loading={featureFlagCopyLoading}
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
    const { projectsWithCurrentFlag } = useValues(featureFlagLogic)
    const { loadProjectsWithCurrentFlag } = useActions(featureFlagLogic)

    useEffect(() => {
        loadProjectsWithCurrentFlag()
    }, [])

    return (
        <div>
            <InfoBanner />
            <FeatureFlagCopySection />
            <LemonTable
                loading={false}
                dataSource={projectsWithCurrentFlag}
                columns={getColumns()}
                emptyState="This feature flag is not being used in any other project."
            />
        </div>
    )
}
