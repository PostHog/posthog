import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonButton, LemonSelect } from '@posthog/lemon-ui'
import { IconArrowRight, IconSync } from 'lib/lemon-ui/icons'
import { useActions, useValues } from 'kea'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { featureFlagLogic } from './featureFlagLogic'
import { organizationLogic } from '../organizationLogic'
import { teamLogic } from 'scenes/teamLogic'
import { useEffect } from 'react'

const getColumns = (): LemonTableColumns<Record<string, string>> => {
    const { currentTeamId } = useValues(teamLogic)

    return [
        {
            title: 'Project',
            dataIndex: 'project_name',
            render: (dataValue, record) =>
                Number(record.project_id) === currentTeamId ? `${dataValue} (current)` : dataValue,
        },
        {
            title: 'Flag status',
            dataIndex: 'active',
            render: (dataValue) => {
                return dataValue ? 'active' : 'disabled'
            },
        },
    ]
}

export default function FeatureFlagProjects(): JSX.Element {
    const { featureFlag, copyDestinationProject, projectsWithCurrentFlag } = useValues(featureFlagLogic)
    const { setCopyDestinationProject, loadProjectsWithCurrentFlag } = useActions(featureFlagLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { currentTeam } = useValues(teamLogic)

    useEffect(() => {
        loadProjectsWithCurrentFlag()
    }, [])

    return (
        <div>
            <h3 className="l3">Feature flag copy</h3>
            <div className="ant-row">Copy your flag and its configuration to another project.</div>
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
                    <LemonButton type="primary" icon={<IconSync />}>
                        Copy
                    </LemonButton>
                </div>
            </div>
            <LemonBanner type="warning" className="mb-6">
                By performing the copy, you may overwrite your existing Feature Flag configuration in another project.
            </LemonBanner>
            <LemonTable
                loading={false}
                dataSource={projectsWithCurrentFlag}
                columns={getColumns()}
                emptyState="This feature flag is not being used in any other project."
            />
        </div>
    )
}
