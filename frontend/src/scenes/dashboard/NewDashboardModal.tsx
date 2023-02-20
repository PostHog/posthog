import { useActions, useValues } from 'kea'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
// import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
// import { FEATURE_FLAGS } from 'lib/constants'
import { dashboardTemplatesLogic } from 'scenes/dashboard/dashboards/templates/dashboardTemplatesLogic'
import { DashboardTemplateVariables } from './DashboardTemplateVariables'
import { LemonButton } from '@posthog/lemon-ui'
import { dashboardTemplateVariablesLogic } from './DashboardTemplateVariablesLogic'
import { DashboardTemplateType } from '~/types'

function TemplateItem({
    template,
    onClick,
}: {
    template: Pick<DashboardTemplateType, 'template_name' | 'dashboard_description' | 'image_url'>
    onClick: () => void
}): JSX.Element {
    return (
        <div
            className="cursor-pointer border-2 rounded"
            onClick={onClick}
            style={{
                width: '240px',
                height: '210px',
            }}
        >
            <div className="w-full h-120 overflow-hidden">
                <img className="w-full h-full object-cover" src={template?.image_url} alt="cover photo" />
            </div>

            <div className="p-2">
                <p className="truncate mb-1">{template?.template_name}</p>
                <p className="text-muted-alt text-xs line-clamp-2">{template?.dashboard_description ?? ' '}</p>
            </div>
        </div>
    )
}

export function DashboardTemplatePreview(): JSX.Element {
    const { activeDashboardTemplate } = useValues(newDashboardLogic)
    const { variables } = useValues(dashboardTemplateVariablesLogic)
    const { createDashboardFromTemplate, clearActiveDashboardTemplate } = useActions(newDashboardLogic)

    return (
        <div>
            <h3>{activeDashboardTemplate?.template_name}</h3>
            <h4>Set up the events for your dashboard.</h4>

            <hr />

            <DashboardTemplateVariables />

            <div className="flex justify-between my-4">
                <LemonButton onClick={clearActiveDashboardTemplate} type="secondary">
                    Back
                </LemonButton>
                <LemonButton
                    onClick={() => {
                        activeDashboardTemplate && createDashboardFromTemplate(activeDashboardTemplate, variables)
                    }}
                    type="primary"
                >
                    Create
                </LemonButton>
            </div>
        </div>
    )
}

export function DashboardTemplateChooser(): JSX.Element {
    const { allTemplates } = useValues(dashboardTemplatesLogic)
    // const { featureFlags } = useValues(featureFlagLogic)
    // const dashboardTemplates = !!featureFlags[FEATURE_FLAGS.DASHBOARD_TEMPLATES]

    // const { dashboardGroup } = useValues(newDashboardLogic)
    // const { setDashboardGroup } = useActions(newDashboardLogic)
    const { addDashboard } = useActions(newDashboardLogic)

    const { setActiveDashboardTemplate } = useActions(newDashboardLogic)

    // const templateGroups = ['Popular Templates', 'Team Templates', 'Your Templates', 'All Templates']
    // const templateGroups = [
    //     {
    //         label: 'Popular Templates',
    //         key: 'popular',
    //     },
    //     {
    //         label: 'Team Templates',
    //         key: 'team',
    //     },
    //     {
    //         label: 'All Templates',
    //         key: 'all',
    //     },
    // ]
    return (
        <div>
            {/* <LemonTabs
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
            /> */}
            <div
                className="flex flex-wrap gap-4"
                style={{
                    maxWidth: '780px',
                }}
            >
                <TemplateItem
                    template={{
                        template_name: 'Blank dashboard',
                        dashboard_description: 'Create a blank dashboard',
                        image_url:
                            'https://posthog.com/static/e49bbe6af9a669f1c07617e5cd2e3229/a764f/marketing-hog.jpg',
                    }}
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
                        template={template}
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
        <LemonModal
            onClose={hideNewDashboardModal}
            isOpen={newDashboardModalVisible}
            title={activeDashboardTemplate ? 'Set up your dashboard' : 'Create a dashboard'}
            description={
                activeDashboardTemplate
                    ? 'Set up the events for your dashboard'
                    : 'Choose a template or start with a blank slate'
            }
        >
            {activeDashboardTemplate ? <DashboardTemplatePreview /> : <DashboardTemplateChooser />}
        </LemonModal>
    )
}
