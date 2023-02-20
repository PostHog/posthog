import { useActions, useValues } from 'kea'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
// import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
// import { FEATURE_FLAGS } from 'lib/constants'
import { dashboardTemplatesLogic } from 'scenes/dashboard/dashboards/templates/dashboardTemplatesLogic'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { DashboardTemplateVariables } from './DashboardTemplateVariables'
import { AppstoreAddOutlined } from '@ant-design/icons'
import { Card } from 'antd'
import { LemonButton } from '@posthog/lemon-ui'
import { dashboardTemplateVariablesLogic } from './DashboardTemplateVariablesLogic'

function TemplateItem({ name, onClick }: { name: string; onClick: () => void }): JSX.Element {
    return (
        <Card title={name} size="small" style={{ width: 200, cursor: 'pointer' }} onClick={onClick}>
            <div style={{ textAlign: 'center', fontSize: 40 }}>
                <AppstoreAddOutlined />
            </div>
        </Card>
    )
}

export function DashboardTemplatePreview(): JSX.Element {
    const { activeDashboardTemplate } = useValues(newDashboardLogic)
    const { variables } = useValues(dashboardTemplateVariablesLogic)
    const { createDashboardFromTemplate, clearActiveDashboardTemplate } = useActions(newDashboardLogic)

    return (
        <div>
            <h3>
                Set up your <strong>{activeDashboardTemplate?.template_name}</strong> dashboard
            </h3>

            <hr />

            <DashboardTemplateVariables />

            <div className="flex justify-between m-4">
                <LemonButton onClick={clearActiveDashboardTemplate} type="secondary">
                    Back
                </LemonButton>
                <LemonButton
                    onClick={() => {
                        activeDashboardTemplate && createDashboardFromTemplate(activeDashboardTemplate, variables)
                    }}
                    type="primary"
                >
                    Create dashboard
                </LemonButton>
            </div>
        </div>
    )
}

export function DashboardTemplateChooser(): JSX.Element {
    const { allTemplates } = useValues(dashboardTemplatesLogic)
    // const { featureFlags } = useValues(featureFlagLogic)
    // const dashboardTemplates = !!featureFlags[FEATURE_FLAGS.DASHBOARD_TEMPLATES]

    const { dashboardGroup } = useValues(newDashboardLogic)
    const { setDashboardGroup, addDashboard } = useActions(newDashboardLogic)

    const { setActiveDashboardTemplate } = useActions(newDashboardLogic)

    // const templateGroups = ['Popular Templates', 'Team Templates', 'Your Templates', 'All Templates']
    const templateGroups = [
        {
            label: 'Popular Templates',
            key: 'popular',
        },
        {
            label: 'Team Templates',
            key: 'team',
        },
        {
            label: 'All Templates',
            key: 'all',
        },
    ]
    return (
        <div>
            <h3>Create a dashboard</h3>
            <LemonTabs
                activeKey={dashboardGroup ?? 'popular'}
                onChange={(key) => {
                    console.log(key)
                    setDashboardGroup(key)
                    console.log(dashboardGroup)
                }}
                tabs={templateGroups.map((group) => ({
                    label: group.label,
                    key: group.key,
                    content: <div />,
                }))}
            />
            <div
                className="flex justify-center items-center gap-4"
                style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(3, 1fr)',
                    gridTemplateRows: 'repeat(3, 1fr)',
                    gap: '10px 10px',
                }}
            >
                <TemplateItem
                    name="Blank dashboard"
                    onClick={() =>
                        addDashboard({
                            name: 'New Dashboard',
                            show: true,
                        })
                    }
                />
                {allTemplates.map((template, index) => (
                    <TemplateItem
                        key={index}
                        name={template.template_name}
                        onClick={() => setActiveDashboardTemplate(template)}
                    />
                ))}
            </div>
        </div>
    )
}

export function NewDashboardModal(): JSX.Element {
    const { hideNewDashboardModal } = useActions(newDashboardLogic)
    const { newDashboardModalVisible } = useValues(newDashboardLogic)

    const { activeDashboardTemplate } = useValues(newDashboardLogic)

    return (
        <LemonModal onClose={hideNewDashboardModal} isOpen={newDashboardModalVisible} width={800}>
            {activeDashboardTemplate ? <DashboardTemplatePreview /> : <DashboardTemplateChooser />}
        </LemonModal>
    )
}
