import { useActions, useValues } from 'kea'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { dashboardTemplatesLogic } from 'scenes/dashboard/dashboards/templates/dashboardTemplatesLogic'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'

function TemplateItem({ name, description }: { name: string; description: string }): JSX.Element {
    return (
        <div
            style={{
                width: '150px',
            }}
        >
            <div
                style={{
                    width: '100%',
                    height: '100px',
                    padding: '10px',
                    backgroundColor: 'var(--muted)',
                    // center the text vertically and horizontally
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                }}
            >
                Image
            </div>
            <div>{name}</div>
            <div>{description}</div>
        </div>
    )
}

export function NewDashboardModal(): JSX.Element {
    const { hideNewDashboardModal } = useActions(newDashboardLogic)
    const { newDashboardModalVisible } = useValues(newDashboardLogic)
    const { templatesList } = useValues(dashboardTemplatesLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const dashboardTemplates = !!featureFlags[FEATURE_FLAGS.DASHBOARD_TEMPLATES]

    const { dashboardGroup } = useValues(newDashboardLogic)
    const { setDashboardGroup } = useActions(newDashboardLogic)

    const templates = dashboardTemplates
        ? templatesList
        : [
              {
                  value: 'DEFAULT_APP',
                  label: 'Product analytics',
                  'data-attr': 'dashboard-select-default-app',
              },
          ]

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
            label: 'Your Templates',
            key: 'your',
        },
        {
            label: 'All Templates',
            key: 'all',
        },
    ]

    return (
        <LemonModal title="New dashboard" onClose={hideNewDashboardModal} isOpen={newDashboardModalVisible} width={800}>
            <div>
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
                    style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        margin: '0 20px',
                    }}
                >
                    <TemplateItem name="Blank dashboard" description="Start from scratch" />
                    {templates.map((template, key) => (
                        <TemplateItem key={key} name={template.label} description="Start from scratch" />
                    ))}
                </div>
            </div>
        </LemonModal>
    )
}
