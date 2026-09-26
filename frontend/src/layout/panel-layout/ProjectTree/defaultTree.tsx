import React, { CSSProperties } from 'react'

import {
    IconAIGateway,
    IconApp,
    IconApps,
    IconArrowUpRight,
    IconAsterisk,
    IconBook,
    IconBrackets,
    IconBrowser,
    IconBug,
    IconCheckbox,
    IconCircleDashed,
    IconClock,
    IconCode,
    IconColumns,
    IconDashboard,
    IconDatabase,
    IconDatabaseBolt,
    IconDecisionTree,
    IconDocument,
    IconDownload,
    IconEndpoints,
    IconExternal,
    IconEye,
    IconFeatures,
    IconFilter,
    IconFlask,
    IconFolder,
    IconFolderMove,
    IconFolderOpen,
    IconGear,
    IconGraduationCap,
    IconGraph,
    IconHeart,
    IconHome,
    IconImage,
    IconLightBulb,
    IconList,
    IconListCheck,
    IconListTree,
    IconLive,
    IconLlmAnalytics,
    IconLlmPromptManagement,
    IconMCP,
    IconMagicWand,
    IconMegaphone,
    IconMessage,
    IconMicrophone,
    IconNotebook,
    IconNotification,
    IconPencil,
    IconPeople,
    IconPerson,
    IconPieChart,
    IconPiggyBank,
    IconPlay,
    IconPlaylist,
    IconPlug,
    IconPullRequest,
    IconPulse,
    IconReceipt,
    IconRewindPlay,
    IconRocket,
    IconScatter,
    IconSearch,
    IconSend,
    IconServer,
    IconShuffle,
    IconSpotlight,
    IconStack,
    IconStar,
    IconStethoscope,
    IconSupport,
    IconTableOfContents,
    IconToggle,
    IconToggleOff,
    IconToolbar,
    IconTrending,
    IconUpload,
    IconUser,
    IconWarning,
} from '@posthog/icons'

import {
    IconBracketsChart,
    IconInsightFunnels,
    IconInsightLifecycle,
    IconInsightRetention,
    IconInsightStickiness,
    IconInsightTrends,
    IconInsightUserPaths,
    IconSelfDriving,
    IconStamphog,
} from 'lib/lemon-ui/icons'
import { urls } from 'scenes/urls'

import {
    fileSystemTypes,
    getTreeItemsGames,
    getTreeItemsMetadata,
    getTreeItemsNew,
    getTreeItemsProducts,
} from '~/products'
import { FileSystemIconType, FileSystemImport } from '~/queries/schema/schema-general'
import { FileSystemIconColor } from '~/types'

const iconTypes: Record<FileSystemIconType, { icon: JSX.Element; iconColor?: FileSystemIconColor }> = {
    default_icon_type: {
        icon: <IconCircleDashed />,
    },
    dashboard: {
        icon: <IconDashboard />,
        iconColor: ['var(--color-product-dashboards-light)'],
    },
    llm_analytics: {
        icon: <IconLlmAnalytics />,
        iconColor: ['var(--color-product-llm-analytics-light)'],
    },
    ai_gateway: {
        icon: <IconAIGateway />,
        iconColor: ['var(--color-product-ai-gateway-light)', 'var(--color-product-ai-gateway-dark)'],
    },
    product_analytics: {
        icon: <IconGraph />,
        iconColor: ['var(--color-product-product-analytics-light)'],
    },
    revenue_analytics: {
        icon: <IconPiggyBank />,
        iconColor: ['var(--color-product-revenue-analytics-light)', 'var(--color-product-revenue-analytics-dark)'],
    },
    revenue_analytics_metadata: {
        icon: <IconPiggyBank />,
        iconColor: ['var(--color-product-revenue-analytics-light)', 'var(--color-product-revenue-analytics-dark)'],
    },
    marketing_settings: {
        icon: <IconMegaphone />,
    },
    marketing_analytics: {
        icon: <IconMegaphone />,
        iconColor: ['var(--color-product-marketing-analytics-light)', 'var(--color-product-marketing-analytics-dark)'],
    },
    customer_analytics: {
        icon: <IconHeart />,
        iconColor: ['var(--color-product-customer-analytics-light)', 'var(--color-product-customer-analytics-dark)'],
    },
    managed_viewsets: {
        icon: <IconColumns />,
        iconColor: ['var(--color-product-managed-viewsets-light)', 'var(--color-product-managed-viewsets-dark)'],
    },
    web_analytics: {
        icon: <IconPieChart />,
        iconColor: ['var(--color-product-web-analytics-light)', 'var(--color-product-web-analytics-dark)'],
    },
    endpoints: {
        icon: <IconEndpoints />,
        iconColor: ['var(--color-product-endpoints-light)', 'var(--color-product-endpoints-dark)'],
    },
    sql_editor: {
        icon: <IconServer />,
        iconColor: ['var(--color-product-data-warehouse-light)'],
    },
    data_modeling: {
        icon: <IconStack />,
        iconColor: ['var(--color-product-models-light)', 'var(--color-product-models-dark)'],
    },
    error_tracking: {
        icon: <IconWarning />,
        iconColor: ['var(--color-product-error-tracking-light)', 'var(--color-product-error-tracking-dark)'],
    },
    heatmap: {
        icon: <IconApp />,
        iconColor: ['var(--color-product-heatmaps-light)', 'var(--color-product-heatmaps-dark)'],
    },
    session_profile: {
        icon: <IconReceipt />,
    },
    session_replay: {
        icon: <IconRewindPlay />,
        iconColor: ['var(--color-product-session-replay-light)', 'var(--color-product-session-replay-dark)'],
    },
    replay_vision: {
        icon: <IconEye />,
        iconColor: ['var(--color-product-session-replay-light)', 'var(--color-product-session-replay-dark)'],
    },
    survey: {
        icon: <IconMessage />,
        iconColor: ['var(--color-product-surveys-light)'],
    },
    product_tour: {
        icon: <IconSpotlight />,
        iconColor: ['var(--color-product-product-tours-light)', 'var(--color-product-product-tours-dark)'],
    },
    user_interview: {
        icon: <IconMicrophone />,
        iconColor: ['var(--color-product-user-interviews-light)', 'var(--color-product-user-interviews-dark)'],
    },
    home: {
        icon: <IconHome />,
    },
    task: {
        icon: <IconCheckbox />,
        iconColor: ['var(--color-product-tasks-light)', 'var(--color-product-tasks-dark)'],
    },
    logs: {
        icon: <IconLive />,
        iconColor: ['var(--color-product-logs-light)', 'var(--color-product-logs-dark)'],
    },
    tracing: {
        icon: <IconListTree />,
        iconColor: ['var(--color-product-tracing-light)', 'var(--color-product-tracing-dark)'],
    },
    metrics: {
        icon: <IconTrending />,
        iconColor: ['var(--color-product-metrics-light)', 'var(--color-product-metrics-dark)'],
    },
    early_access_feature: {
        icon: <IconRocket />,
        iconColor: [
            'var(--color-product-early-access-features-light)',
            'var(--color-product-early-access-features-dark)',
        ],
    },
    experiment: {
        icon: <IconFlask />,
        iconColor: ['var(--color-product-experiments-light)'],
    },
    feature_flag: {
        icon: <IconToggle className="mt-[2px]" />,
        iconColor: ['var(--color-product-feature-flags-light)'],
    },
    feature_flag_off: {
        icon: <IconToggleOff className="mt-[2px]" />,
        iconColor: ['var(--color-bg-fill-switch)'],
    },
    data_pipeline: {
        icon: <IconPlug />,
        iconColor: ['var(--color-product-data-pipeline-light)', 'var(--color-product-data-pipeline-dark)'],
    },
    data_pipeline_metadata: {
        icon: <IconPlug />,
    },
    data_warehouse: {
        icon: <IconDatabase />,
        iconColor: ['var(--color-product-data-warehouse-light)', 'var(--color-product-data-warehouse-dark)'],
    },
    link: {
        icon: <IconExternal />,
        iconColor: ['var(--color-product-links-light)', 'var(--color-product-links-dark)'],
    },
    workflows: {
        icon: <IconDecisionTree />,
        iconColor: ['var(--color-product-workflows-light)', 'var(--color-product-workflows-dark)'],
    },
    broadcasts: {
        icon: <IconSend />,
        iconColor: ['var(--color-product-broadcasts-light)', 'var(--color-product-broadcasts-dark)'],
    },
    notebook: {
        icon: <IconNotebook />,
        iconColor: ['var(--color-product-notebooks-light)', 'var(--color-product-notebooks-dark)'],
    },
    live_debugger: {
        icon: <IconBug />,
        iconColor: ['var(--color-product-live-debugger-light)', 'var(--color-product-live-debugger-dark)'],
    },
    action: {
        icon: <IconPlay />,
    },
    activity: {
        icon: <IconClock />,
    },
    comment: {
        icon: <IconNotification />,
    },
    annotation: {
        icon: <IconPencil />,
        iconColor: ['var(--color-product-annotations-light)', 'var(--color-product-annotations-dark)'],
    },
    event: {
        icon: <IconApps />,
    },
    event_definition: {
        icon: <IconApps />,
        iconColor: ['var(--color-product-event-definitions-light)', 'var(--color-product-event-definitions-dark)'],
    },
    property_definition: {
        icon: <IconAsterisk />,
        iconColor: [
            'var(--color-product-property-definitions-light)',
            'var(--color-product-property-definitions-dark)',
        ],
    },
    ingestion_warning: {
        icon: <IconWarning />,
    },
    persons: {
        icon: <IconPerson />,
    },
    user: {
        icon: <IconUser />,
    },
    cohort: {
        icon: <IconPeople />,
    },
    group: {
        icon: <IconPeople />,
    },
    // The IconInsight* glyphs carry their own multi-color palette (--insight-icon-*);
    // structural parts follow currentColor, so no iconColor override here.
    'insight/funnels': {
        icon: <IconInsightFunnels />,
    },
    'insight/trends': {
        icon: <IconInsightTrends />,
    },
    'insight/retention': {
        icon: <IconInsightRetention />,
    },
    'insight/paths': {
        icon: <IconInsightUserPaths />,
    },
    'insight/lifecycle': {
        icon: <IconInsightLifecycle />,
    },
    'insight/stickiness': {
        icon: <IconInsightStickiness />,
    },
    'insight/hog': {
        icon: <IconBracketsChart />,
    },
    team_activity: {
        icon: <IconNotification />,
        iconColor: ['var(--color-product-activity-light)', 'var(--color-product-activity-dark)'],
    },
    tools: {
        icon: <IconApps />,
    },
    live: {
        icon: <IconLive />,
    },
    chat: {
        icon: <IconFeatures />,
    },
    search: {
        icon: <IconSearch />,
    },
    folder: {
        icon: <IconFolder />,
    },
    folder_open: {
        icon: <IconFolderOpen />,
    },
    conversations: {
        icon: <IconSupport />,
        iconColor: ['var(--color-product-support-light)', 'var(--color-product-support-dark)'],
    },
    toolbar: {
        icon: <IconToolbar />,
        iconColor: ['var(--color-product-toolbar-light)', 'var(--color-product-toolbar-dark)'],
    },
    settings: {
        icon: <IconGear />,
    },
    health: {
        icon: <IconStethoscope />,
    },
    inbox: {
        icon: <IconSelfDriving />,
    },
    sdk_health: {
        icon: <IconCode />,
    },
    pipeline_status: {
        icon: <IconDatabase />,
    },
    llm_evaluations: {
        icon: <IconListCheck />,
        iconColor: ['var(--color-product-llm-evaluations-light)', 'var(--color-product-llm-evaluations-dark)'],
    },
    llm_tags: {
        icon: <IconList />,
        iconColor: ['var(--color-product-llm-tags-light)', 'var(--color-product-llm-tags-dark)'],
    },
    llm_datasets: {
        icon: <IconDocument />,
        iconColor: ['var(--color-product-llm-datasets-light)', 'var(--color-product-llm-datasets-dark)'],
    },
    llm_prompts: {
        icon: <IconLlmPromptManagement />,
        iconColor: ['var(--color-product-llm-prompts-light)', 'var(--color-product-llm-prompts-dark)'],
    },
    llm_clusters: {
        icon: <IconScatter />,
        iconColor: ['var(--color-product-llm-clusters-light)', 'var(--color-product-llm-clusters-dark)'],
    },
    llm_playground: {
        icon: <IconPlaylist />,
        iconColor: ['var(--color-product-llm-playground-light)', 'var(--color-product-llm-playground-dark)'],
    },
    mcp_analytics: {
        icon: <IconMCP />,
        iconColor: ['var(--color-product-mcp-analytics-light)', 'var(--color-product-mcp-analytics-dark)'],
    },
    visual_review: {
        icon: <IconImage />,
        iconColor: ['var(--color-product-visual-review-light)', 'var(--color-product-visual-review-dark)'],
    },
    code_review: {
        icon: <IconPullRequest />,
        iconColor: ['var(--color-product-code-review-light)', 'var(--color-product-code-review-dark)'],
    },
    stamphog: {
        icon: <IconStamphog />,
    },
    exports: {
        icon: <IconDownload />,
    },
    pulse: {
        icon: <IconPulse />,
        iconColor: ['var(--color-product-activity-light)', 'var(--color-product-activity-dark)'],
    },
    skill: {
        icon: <IconGraduationCap />,
        iconColor: ['var(--color-product-skills-light)', 'var(--color-product-skills-dark)'],
    },
    wizard: {
        icon: <IconMagicWand />,
        iconColor: ['var(--color-product-wizard-light)', 'var(--color-product-wizard-dark)'],
    },
    data_catalog: {
        icon: <IconTableOfContents />,
        iconColor: ['var(--color-product-data-catalog-light)', 'var(--color-product-data-catalog-dark)'],
    },
    warehouse_destination: {
        icon: <IconUpload />,
        iconColor: [
            'var(--color-product-warehouse-destinations-light)',
            'var(--color-product-warehouse-destinations-dark)',
        ],
    },
    warehouse_property: {
        icon: <IconDatabaseBolt />,
        iconColor: [
            'var(--color-product-warehouse-properties-light)',
            'var(--color-product-warehouse-properties-dark)',
        ],
    },
    data_source: {
        icon: <IconDownload />,
        iconColor: ['var(--color-product-sources-light)', 'var(--color-product-sources-dark)'],
    },
    data_destination: {
        icon: <IconArrowUpRight />,
        iconColor: ['var(--color-product-destinations-light)', 'var(--color-product-destinations-dark)'],
    },
    data_transformation: {
        icon: <IconShuffle />,
        iconColor: ['var(--color-product-transformations-light)', 'var(--color-product-transformations-dark)'],
    },
    event_filter: {
        icon: <IconFilter />,
        iconColor: ['var(--color-product-event-filtering-light)', 'var(--color-product-event-filtering-dark)'],
    },
    managed_migration: {
        icon: <IconFolderMove />,
        iconColor: ['var(--color-product-managed-migrations-light)', 'var(--color-product-managed-migrations-dark)'],
    },
    web_script: {
        icon: <IconCode />,
        iconColor: ['var(--color-product-web-scripts-light)', 'var(--color-product-web-scripts-dark)'],
    },
    core_event: {
        icon: <IconStar />,
        iconColor: ['var(--color-product-core-events-light)', 'var(--color-product-core-events-dark)'],
    },
    property_group: {
        icon: <IconFolder />,
        iconColor: ['var(--color-product-property-groups-light)', 'var(--color-product-property-groups-dark)'],
    },
    mcp_server: {
        icon: <IconPlug />,
        iconColor: ['var(--color-product-mcp-servers-light)', 'var(--color-product-mcp-servers-dark)'],
    },
    streamlit_app: {
        icon: <IconBrowser />,
        iconColor: ['var(--color-product-data-pipeline-light)', 'var(--color-product-data-pipeline-dark)'],
    },
    sql_variable: {
        icon: <IconBrackets />,
        iconColor: ['var(--color-product-sql-variables-light)', 'var(--color-product-sql-variables-dark)'],
    },
    business_knowledge: {
        icon: <IconLightBulb />,
        iconColor: ['var(--color-product-business-knowledge-light)', 'var(--color-product-business-knowledge-dark)'],
    },
}

const getIconColor = (type?: string, colorOverride?: FileSystemIconColor): FileSystemIconColor => {
    // Manifest color takes precedence
    const fileSystemColor = (fileSystemTypes as unknown as Record<string, { iconColor?: FileSystemIconColor }>)[
        type as keyof typeof fileSystemTypes
    ]?.iconColor

    // Fallback to iconTypes if no manifest color is provided
    const iconTypeColor = type && iconTypes[type as keyof typeof iconTypes]?.iconColor

    // If we have a color override, use it
    // Otherwise, use the above colors in order of precedence
    const color = colorOverride ?? fileSystemColor ?? iconTypeColor ?? ['currentColor', 'currentColor']
    return color.length === 1 ? [color[0], color[0]] : (color as FileSystemIconColor)
}

type ProductIconWrapperProps = {
    type?: string
    children: React.ReactNode
    // Light and dark color overrides
    colorOverride?: FileSystemIconColor
}

export const ProductIconWrapper = ({ type, children, colorOverride }: ProductIconWrapperProps): JSX.Element => {
    const [light, dark] = getIconColor(type, colorOverride)

    // By default icons will not be colorful, to add color, wrap the icon with the class: "group/colorful-product-icons colorful-product-icons-true"
    return (
        <span
            className="flex items-center group-[.colorful-product-icons-true]/colorful-product-icons:text-[var(--product-icon-color-light)] dark:group-[.colorful-product-icons-true]/colorful-product-icons:text-[var(--product-icon-color-dark)]"
            // eslint-disable-next-line react/forbid-dom-props
            style={
                {
                    '--product-icon-color-light': light,
                    '--product-icon-color-dark': dark,
                } as CSSProperties
            }
        >
            {children}
        </span>
    )
}

export function iconForType(type?: FileSystemIconType, colorOverride?: FileSystemIconColor): JSX.Element {
    if (!type) {
        return (
            <ProductIconWrapper type={type} colorOverride={colorOverride}>
                <IconBook />
            </ProductIconWrapper>
        )
    }

    // Check if the type exists in fileSystemTypes manifest and resolve iconType from there
    const fileSystemType = fileSystemTypes[type as keyof typeof fileSystemTypes]
    if (fileSystemType?.iconType && fileSystemType.iconType in iconTypes) {
        return (
            <ProductIconWrapper type={fileSystemType.iconType} colorOverride={colorOverride}>
                {iconTypes[fileSystemType.iconType as keyof typeof iconTypes].icon}
            </ProductIconWrapper>
        )
    }

    if (type in iconTypes) {
        return (
            <ProductIconWrapper type={type} colorOverride={colorOverride}>
                {iconTypes[type as keyof typeof iconTypes].icon}
            </ProductIconWrapper>
        )
    }

    // Handle group type indices (group_0, group_1, etc.)
    if (type.startsWith('group_')) {
        const index = parseInt(type.split('_')[1], 10)
        if (!isNaN(index)) {
            return (
                <ProductIconWrapper type="group" colorOverride={colorOverride}>
                    <span className="relative flex items-center">
                        <IconPeople />
                        <div className="absolute -bottom-0.5 -right-1 z-10 flex h-[1.5em] w-[1.5em] items-center justify-center rounded-full bg-surface-tertiary text-[0.45em] font-[700] leading-none">
                            {index}
                        </div>
                    </span>
                </ProductIconWrapper>
            )
        }
    }

    // Handle hog_function types
    if (type.startsWith('hog_function/')) {
        return (
            <ProductIconWrapper type="plug" colorOverride={colorOverride}>
                <IconPlug />
            </ProductIconWrapper>
        )
    }

    // Default
    return (
        <ProductIconWrapper type={type} colorOverride={colorOverride}>
            <IconBook />
        </ProductIconWrapper>
    )
}

export const getDefaultTreeNew = (): FileSystemImport[] =>
    [...getTreeItemsNew()].sort((a, b) => a.path.localeCompare(b.path, undefined, { sensitivity: 'accent' }))
export const getDefaultTreeData = (): FileSystemImport[] =>
    [...getTreeItemsMetadata()].sort((a, b) => a.path.localeCompare(b.path, undefined, { sensitivity: 'accent' }))
export const getDefaultTreeProducts = (): FileSystemImport[] =>
    [...getTreeItemsProducts()].sort((a, b) => a.path.localeCompare(b.path, undefined, { sensitivity: 'accent' }))
export const getDefaultTreeGames = (): FileSystemImport[] =>
    [...getTreeItemsGames()].sort((a, b) => a.path.localeCompare(b.path, undefined, { sensitivity: 'accent' }))

export const getDefaultTreeDataAndPeople = (): FileSystemImport[] =>
    [...getDefaultTreeData(), ...getDefaultTreePersons()].sort((a, b) =>
        a.path.localeCompare(b.path, undefined, { sensitivity: 'accent' })
    )

export const getDefaultTreePersons = (): FileSystemImport[] => [
    {
        path: 'Persons',
        category: 'People',
        iconType: 'persons',
        href: urls.persons(),
        visualOrder: 10,
        sceneKey: 'Persons',
        sceneKeys: ['Person', 'Persons'],
    },
    {
        path: 'Cohorts',
        category: 'People',
        type: 'cohort',
        href: urls.cohorts(),
        visualOrder: 20,
        sceneKey: 'Cohorts',
        sceneKeys: ['Cohort', 'Cohorts'],
    },
]
