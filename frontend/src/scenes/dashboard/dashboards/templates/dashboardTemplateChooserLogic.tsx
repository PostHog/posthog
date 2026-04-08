import { actions, connect, kea, key, listeners, path, props } from 'kea'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'

import { DashboardTemplateType } from '~/types'

import type { dashboardTemplateChooserLogicType } from './dashboardTemplateChooserLogicType'
import { runBlankDashboardFlow, runDashboardTemplateClickFlow } from './dashboardTemplateCreationFlows'
import { DashboardTemplateProps, dashboardTemplatesLogic } from './dashboardTemplatesLogic'

export type DashboardTemplateChooserExperimentVariant = 'control' | 'simple' | 'new'

export type DashboardTemplateChooserLogicProps = DashboardTemplateProps & {
    experimentVariant: DashboardTemplateChooserExperimentVariant
}

function availabilityContextsKey(contexts: DashboardTemplateProps['availabilityContexts']): string {
    if (!contexts?.length) {
        return 'any'
    }
    return [...contexts].sort().join(',')
}

export const dashboardTemplateChooserLogic = kea<dashboardTemplateChooserLogicType>([
    path(['scenes', 'dashboard', 'dashboards', 'templates', 'dashboardTemplateChooserLogic']),
    props({} as DashboardTemplateChooserLogicProps),
    key(
        (p: DashboardTemplateChooserLogicProps) =>
            `${p.scope ?? 'default'}|${p.experimentVariant}|${availabilityContextsKey(p.availabilityContexts)}`
    ),
    connect((props: DashboardTemplateChooserLogicProps) => ({
        values: [
            dashboardTemplatesLogic({ scope: props.scope ?? 'default' }),
            ['allTemplates', 'allTemplatesLoading', 'templateFilter'],
            newDashboardLogic,
            ['isLoading', 'newDashboardModalVisible'],
        ],
        actions: [
            dashboardTemplatesLogic({ scope: props.scope ?? 'default' }),
            ['setTemplateFilter'],
            newDashboardLogic,
            [
                'setActiveDashboardTemplate',
                'createDashboardFromTemplate',
                'addDashboard',
                'setIsLoading',
                'showVariableSelectModal',
            ],
        ],
    })),
    actions({
        templateTileClicked: (template: DashboardTemplateType, tileLocation: 'main_grid' | 'featured_row') => ({
            template,
            tileLocation,
        }),
        blankTileClicked: (tileLocation: 'main_grid' | 'featured_row') => ({ tileLocation }),
    }),
    listeners(({ actions, values, props }) => ({
        templateTileClicked: ({ template, tileLocation }) => {
            if (values.isLoading) {
                return
            }
            posthog.capture('dashboard template chooser template clicked', {
                experiment_variant: props.experimentVariant,
                selection_type: 'template',
                tile_location: tileLocation,
                template_id: template.id,
                template_name: template.template_name.toLowerCase(),
                is_featured: template.is_featured === true,
                $feature_flag: FEATURE_FLAGS.DASHBOARD_TEMPLATE_CHOOSER_EXPERIMENT,
                $feature_flag_response: props.experimentVariant,
            })
            runDashboardTemplateClickFlow(template, {
                isLoading: values.isLoading,
                newDashboardModalVisible: values.newDashboardModalVisible,
                redirectAfterCreation: props.redirectAfterCreation ?? true,
                setIsLoading: actions.setIsLoading,
                createDashboardFromTemplate: actions.createDashboardFromTemplate,
                showVariableSelectModal: actions.showVariableSelectModal,
                setActiveDashboardTemplate: actions.setActiveDashboardTemplate,
                onItemClick: props.onItemClick,
            })
        },
        blankTileClicked: ({ tileLocation }) => {
            if (values.isLoading) {
                return
            }
            posthog.capture('dashboard template chooser template clicked', {
                experiment_variant: props.experimentVariant,
                selection_type: 'blank',
                tile_location: tileLocation,
                $feature_flag: FEATURE_FLAGS.DASHBOARD_TEMPLATE_CHOOSER_EXPERIMENT,
                $feature_flag_response: props.experimentVariant,
            })
            runBlankDashboardFlow({
                isLoading: values.isLoading,
                setIsLoading: actions.setIsLoading,
                addDashboard: actions.addDashboard,
            })
        },
    })),
])
