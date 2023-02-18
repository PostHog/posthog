import { useActions, useValues } from 'kea'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { dashboardTemplatesLogic } from 'scenes/dashboard/dashboards/templates/dashboardTemplatesLogic'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'

function TemplateItem({
    name,
    description,
    onClick,
}: {
    templateId: string
    name: string
    description: string
    onClick: (template: string) => void
}): JSX.Element {
    return (
        <div
            style={{
                width: '150px',
            }}
            onClick={onClick}
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

export function DashboardTemplatePreview(): JSX.Element {
    const { activeDashboardTemplate } = useValues(newDashboardLogic)
    const { setActiveDashboardTemplate, addDashboard } = useActions(newDashboardLogic)

    return (
        <div>
            <h3>Create a dashboard</h3>
            <div>Preview</div>
            <div>{activeDashboardTemplate}</div>
            <div
                style={{
                    width: '100px',
                    height: '100px',
                    backgroundColor: 'var(--muted)',
                }}
            />
            <button onClick={() => setActiveDashboardTemplate('')}>Close</button>
            <button
                onClick={() => {
                    addDashboard({
                        name: 'New dashboard',
                        show: true,
                        useTemplate: activeDashboardTemplate ?? '',
                    })
                }}
            >
                Create
            </button>
        </div>
    )
}

export function DashboardTemplateChooser(): JSX.Element {
    const { templatesList } = useValues(dashboardTemplatesLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const dashboardTemplates = !!featureFlags[FEATURE_FLAGS.DASHBOARD_TEMPLATES]

    const { dashboardGroup } = useValues(newDashboardLogic)
    const { setDashboardGroup } = useActions(newDashboardLogic)

    const { setActiveDashboardTemplate } = useActions(newDashboardLogic)

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
                style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    margin: '0 20px',
                }}
            >
                <TemplateItem
                    name="Blank dashboard"
                    description="Start from scratch"
                    templateId="blank"
                    onClick={() => setActiveDashboardTemplate('')}
                />
                {templates.map((template, index) => (
                    <TemplateItem
                        key={index}
                        name={template.label}
                        description="Start from scratch"
                        onClick={() => setActiveDashboardTemplate(template.value)}
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
            {activeDashboardTemplate !== undefined ? <DashboardTemplatePreview /> : <DashboardTemplateChooser />}
        </LemonModal>
    )
}
