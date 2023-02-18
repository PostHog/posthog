import { useActions, useValues } from 'kea'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { dashboardTemplatesLogic } from 'scenes/dashboard/dashboards/templates/dashboardTemplatesLogic'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { DashboardTemplateVariables } from './DashboardTemplateVariables'

function TemplateItem({
    templateId,
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
            onClick={() => onClick(templateId)}
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
            <h3>
                Set up your <strong>{activeDashboardTemplate}</strong> dashboard
            </h3>

            <hr />

            <DashboardTemplateVariables />
            <button onClick={() => setActiveDashboardTemplate('')}>Close</button>
            <button
                onClick={() => {
                    addDashboard({
                        name: 'Test',
                        show: true,
                        useTemplate: activeDashboardTemplate == 'BLANK' ? '' : activeDashboardTemplate,
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
                    templateId="BLANK"
                    onClick={setActiveDashboardTemplate}
                />
                {templates.map((template, index) => (
                    <TemplateItem
                        key={index}
                        name={template.label}
                        description="Start from scratch"
                        templateId={template.value}
                        onClick={setActiveDashboardTemplate}
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
