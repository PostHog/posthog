import { useActions, useValues } from 'kea'

import {
    IconApps,
    IconBug,
    IconCode2,
    IconCursor,
    IconDashboard,
    IconDatabase,
    IconFlask,
    IconHome,
    IconInfo,
    IconLive,
    IconMessage,
    IconNotebook,
    IconNotification,
    IconPieChart,
    IconPiggyBank,
    IconPlus,
    IconRewindPlay,
    IconRocket,
    IconSpotlight,
    IconToggle,
    IconTrends,
    IconWarning,
} from '@posthog/icons'
import { LemonButton, LemonDropdown, LemonSelect, LemonTable, Tooltip } from '@posthog/lemon-ui'

import { getAccessControlTooltip } from 'lib/utils/accessControlUtils'

import { APIScopeObject, AccessControlLevel } from '~/types'

import { accessControlsLogic } from './accessControlsLogic'

const SCOPE_ICON_MAP: Record<string, React.ReactElement> = {
    project: <IconHome />,
    action: <IconCursor />,
    activity_log: <IconNotification />,
    dashboard: <IconDashboard />,
    early_access_feature: <IconRocket />,
    endpoint: <IconCode2 />,
    error_tracking: <IconWarning />,
    event_definition: <IconApps />,
    experiment: <IconFlask />,
    external_data_source: <IconDatabase />,
    feature_flag: <IconToggle />,
    insight: <IconTrends />,
    live_debugger: <IconBug />,
    logs: <IconLive />,
    notebook: <IconNotebook />,
    product_tour: <IconSpotlight />,
    property_definition: <IconApps />,
    revenue_analytics: <IconPiggyBank />,
    session_recording: <IconRewindPlay />,
    survey: <IconMessage />,
    task: <IconBug />,
    web_analytics: <IconPieChart />,
}

export function AccessControlDefaultSettings({ projectId }: { projectId: string }): JSX.Element {
    const logic = accessControlsLogic({ projectId })
    const {
        resourcesWithProject,
        getLevelOptionsForResource,
        allRows,
        loading,
        canEditAccessControls,
        canEditRoleBasedAccessControls,
    } = useValues(logic)
    const { updateAccessControlDefault, updateResourceAccessControls } = useActions(logic)

    const defaultRow = allRows.find((row) => row.id === 'default')
    const mappedLevels =
        defaultRow?.levels.reduce(
            (prev, l) => Object.assign(prev, { [l.resourceKey]: l.level }),
            {} as Record<APIScopeObject, AccessControlLevel | null>
        ) || {}

    return (
        <LemonTable
            dataSource={resourcesWithProject}
            loading={loading}
            columns={[
                {
                    title: 'Feature',
                    key: 'label',
                    render: function RenderFeature(_, resource) {
                        const tooltipText = getAccessControlTooltip(resource.key)
                        return (
                            <div className="font-medium flex items-center gap-2">
                                <span className="text-lg flex items-center text-muted-alt">
                                    {SCOPE_ICON_MAP[resource.key]}
                                </span>
                                {resource.label}
                                {tooltipText && (
                                    <Tooltip title={tooltipText}>
                                        <IconInfo className="text-sm text-muted" />
                                    </Tooltip>
                                )}
                            </div>
                        )
                    },
                },
                {
                    title: 'Access',
                    key: 'access',
                    align: 'right',
                    render: function RenderAccess(_, resource) {
                        const canEdit =
                            resource.key === 'project' ? canEditAccessControls : canEditRoleBasedAccessControls
                        const value = mappedLevels[resource.key] ?? null

                        if (resource.key !== 'project' && value === null) {
                            return (
                                <LemonDropdown
                                    placement="bottom-end"
                                    overlay={
                                        <div className="flex flex-col">
                                            {getLevelOptionsForResource(resource.key).map((option) => (
                                                <LemonButton
                                                    key={option.value}
                                                    size="small"
                                                    className="w-36"
                                                    fullWidth
                                                    disabledReason={option.disabledReason}
                                                    onClick={() => {
                                                        updateResourceAccessControls(
                                                            [
                                                                {
                                                                    resource: resource.key,
                                                                    access_level: option.value as AccessControlLevel,
                                                                    role: null,
                                                                    organization_member: null,
                                                                },
                                                            ],
                                                            'default'
                                                        )
                                                    }}
                                                >
                                                    {option.label}
                                                </LemonButton>
                                            ))}
                                        </div>
                                    }
                                >
                                    <LemonButton
                                        size="small"
                                        type="tertiary"
                                        icon={<IconPlus />}
                                        sideIcon={null}
                                        disabled={loading || !canEdit}
                                        className="ml-auto my-0.5 w-36"
                                    >
                                        Add override
                                    </LemonButton>
                                </LemonDropdown>
                            )
                        }

                        return (
                            <LemonSelect
                                dropdownPlacement="bottom-end"
                                placeholder="No override"
                                value={value}
                                disabled={loading || !canEdit}
                                size="small"
                                className="ml-auto w-36 my-0.5"
                                onChange={(newValue) => {
                                    if (resource.key === 'project') {
                                        updateAccessControlDefault(newValue as AccessControlLevel)
                                    } else {
                                        updateResourceAccessControls(
                                            [
                                                {
                                                    resource: resource.key,
                                                    access_level: newValue as AccessControlLevel | null,
                                                    role: null,
                                                    organization_member: null,
                                                },
                                            ],
                                            'default'
                                        )
                                    }
                                }}
                                options={[
                                    ...(resource.key !== 'project' ? [{ value: null, label: 'No override' }] : []),
                                    ...(getLevelOptionsForResource(resource.key) as any[]),
                                ]}
                            />
                        )
                    },
                },
            ]}
        />
    )
}
