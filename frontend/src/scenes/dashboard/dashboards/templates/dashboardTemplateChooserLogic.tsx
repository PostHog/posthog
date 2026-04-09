import { actions, connect, kea, key, listeners, path, props, selectors } from 'kea'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'

import { DashboardTemplateType, TemplateAvailabilityContext } from '~/types'

import type { dashboardTemplateChooserLogicType } from './dashboardTemplateChooserLogicType'
import { runBlankDashboardFlow, runDashboardTemplateClickFlow } from './dashboardTemplateCreationFlows'
import { DashboardTemplateProps, dashboardTemplatesLogic } from './dashboardTemplatesLogic'

export type DashboardTemplateChooserExperimentVariant = 'control' | 'simple' | 'new'

/** Single place for flag → chooser experiment variant (modal toolbar + grid must agree on chooser logic key). */
export function resolveDashboardTemplateChooserExperimentVariant(
    raw: unknown
): DashboardTemplateChooserExperimentVariant {
    return raw === 'simple' || raw === 'new' || raw === 'control' ? raw : 'new'
}

export type DashboardTemplateChooserLogicProps = DashboardTemplateProps & {
    experimentVariant: DashboardTemplateChooserExperimentVariant
}

function availabilityContextsKey(contexts: DashboardTemplateProps['availabilityContexts']): string {
    if (!contexts?.length) {
        return 'any'
    }
    return [...contexts].sort().join(',')
}

function isTeamTemplate(template: DashboardTemplateType): boolean {
    return template.scope === 'team'
}

function filterTemplatesByAvailability(
    allTemplates: DashboardTemplateType[],
    availabilityContexts: DashboardTemplateProps['availabilityContexts']
): DashboardTemplateType[] {
    if (!availabilityContexts?.length) {
        return allTemplates
    }
    return allTemplates.filter((template) =>
        availabilityContexts.some((context: TemplateAvailabilityContext) =>
            template.availability_contexts?.includes(context)
        )
    )
}

function computeShowBlankTile(availabilityContexts: DashboardTemplateProps['availabilityContexts']): boolean {
    return (
        !availabilityContexts ||
        availabilityContexts.length === 0 ||
        availabilityContexts.includes(TemplateAvailabilityContext.GENERAL)
    )
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
        templateTileClicked: (
            template: DashboardTemplateType,
            tileLocation: 'main_grid' | 'featured_row' | 'team_section'
        ) => ({
            template,
            tileLocation,
        }),
        blankTileClicked: (tileLocation: 'main_grid' | 'featured_row' | 'modal_toolbar') => ({ tileLocation }),
    }),
    selectors(({ props }) => ({
        filteredTemplates: [
            (s) => [s.allTemplates],
            (raw) => filterTemplatesByAvailability(raw, props.availabilityContexts),
        ],
        showBlankTile: [() => [], () => computeShowBlankTile(props.availabilityContexts)],
        teamTemplates: [(s) => [s.filteredTemplates], (visible) => visible.filter(isTeamTemplate)],
        officialTemplates: [(s) => [s.filteredTemplates], (visible) => visible.filter((t) => !isTeamTemplate(t))],
        featuredTemplates: [(s) => [s.officialTemplates], (official) => official.filter((t) => t.is_featured === true)],
        nonFeaturedOfficial: [
            (s) => [s.officialTemplates],
            (official) => official.filter((t) => t.is_featured !== true),
        ],
        hasActiveFilter: [(s) => [s.templateFilter], (filterText) => filterText.trim().length > 0],
        showDashedEmptyState: [
            (s) => [s.allTemplatesLoading, s.filteredTemplates],
            (loading, visible) => !loading && visible.length === 0,
        ],
        showOfficialGrid: [
            (s) => [s.allTemplatesLoading, s.officialTemplates],
            (loading, official) => loading || official.length > 0,
        ],
        allMatchesInFeaturedSection: [
            (s) => [s.nonFeaturedOfficial, s.featuredTemplates],
            (nonFeatured, featured) => nonFeatured.length === 0 && featured.length > 0,
        ],
        showOfficialSection: [
            (s) => [s.allTemplatesLoading, s.allMatchesInFeaturedSection, s.nonFeaturedOfficial],
            (loading, allMatchesPopular, nonFeatured) => loading || allMatchesPopular || nonFeatured.length > 0,
        ],
    })),
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
                template_scope: template.scope ?? null,
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
