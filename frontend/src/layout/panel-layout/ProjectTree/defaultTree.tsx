import React, { CSSProperties } from 'react'

import {
    IconAI,
    IconApp,
    IconApps,
    IconBook,
    IconBug,
    IconCode2,
    IconCursor,
    IconDashboard,
    IconDatabase,
    IconExternal,
    IconFlask,
    IconFunnels,
    IconGraph,
    IconHogQL,
    IconHome,
    IconLifecycle,
    IconLive,
    IconMegaphone,
    IconMessage,
    IconNotebook,
    IconNotification,
    IconPeople,
    IconPieChart,
    IconPiggyBank,
    IconPlug,
    IconRetention,
    IconRewindPlay,
    IconRocket,
    IconServer,
    IconStickiness,
    IconToggle,
    IconTrends,
    IconUserPaths,
    IconWarning,
} from '@posthog/icons'

import { FEATURE_FLAGS } from 'lib/constants'
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
    dashboard: {
        icon: <IconDashboard />,
        iconColor: ['var(--color-product-dashboards-light)'],
    },
    llm_analytics: {
        icon: <IconAI />,
        iconColor: ['var(--color-product-llm-analytics-light)'],
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
    },
    marketing_settings: {
        icon: <IconMegaphone />,
    },
    web_analytics: {
        icon: <IconPieChart />,
        iconColor: ['var(--color-product-web-analytics-light)', 'var(--color-product-web-analytics-dark)'],
    },
    endpoints: {
        icon: <IconCode2 />,
        iconColor: ['var(--color-product-endpoints-light)', 'var(--color-product-endpoints-dark)'],
    },
    sql_editor: {
        icon: <IconServer />,
        iconColor: ['var(--color-product-data-warehouse-light)'],
    },
    error_tracking: {
        icon: <IconWarning />,
        iconColor: ['var(--color-product-error-tracking-light)', 'var(--color-product-error-tracking-dark)'],
    },
    heatmap: {
        icon: <IconApp />,
        iconColor: ['var(--color-product-heatmaps-light)', 'var(--color-product-heatmaps-dark)'],
    },
    session_replay: {
        icon: <IconRewindPlay />,
        iconColor: ['var(--color-product-session-replay-light)', 'var(--color-product-session-replay-dark)'],
    },
    survey: {
        icon: <IconMessage />,
        iconColor: ['var(--color-product-surveys-light)'],
    },
    user_interview: {
        icon: <IconApp />,
        iconColor: ['var(--color-product-user-interviews-light)'],
    },
    home: {
        icon: <IconHome />,
    },
    task: {
        icon: <IconBug />,
    },
    logs: {
        icon: <IconLive />,
        iconColor: ['var(--color-product-logs-light)'],
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
        icon: <IconToggle />,
        iconColor: ['var(--color-product-feature-flags-light)'],
    },
    data_pipeline: {
        icon: <IconPlug />,
        iconColor: ['var(--color-product-data-pipeline-light)'],
    },
    data_pipeline_metadata: {
        icon: <IconPlug />,
    },
    data_warehouse: {
        icon: <IconDatabase />,
        iconColor: ['var(--color-product-data-warehouse-light)'],
    },
    link: {
        icon: <IconExternal />,
        iconColor: ['var(--color-product-links-light)', 'var(--color-product-links-dark)'],
    },
    messaging: {
        icon: <IconMessage />,
        iconColor: ['var(--color-product-messaging-light)', 'var(--color-product-messaging-dark)'],
    },
    notebook: {
        icon: <IconNotebook />,
    },
    action: {
        icon: <IconCursor />,
    },
    comment: {
        icon: <IconNotification />,
    },
    annotation: {
        icon: <IconNotification />,
    },
    event_definition: {
        icon: <IconApps />,
    },
    property_definition: {
        icon: <IconApps />,
    },
    ingestion_warning: {
        icon: <IconWarning />,
    },
    person: {
        icon: <IconPeople />,
    },
    cohort: {
        icon: <IconPeople />,
    },
    group: {
        icon: <IconPeople />,
    },
    'insight/funnels': {
        icon: <IconFunnels />,
        iconColor: ['var(--color-insight-funnel-light)'],
    },
    'insight/trends': {
        icon: <IconTrends />,
        iconColor: ['var(--color-insight-trends-light)'],
    },
    'insight/retention': {
        icon: <IconRetention />,
        iconColor: ['var(--color-insight-retention-light)'],
    },
    'insight/paths': {
        icon: <IconUserPaths />,
        iconColor: ['var(--color-insight-user-paths-light)', 'var(--color-user-paths-dark)'],
    },
    'insight/lifecycle': {
        icon: <IconLifecycle />,
        iconColor: ['var(--color-insight-lifecycle-light)'],
    },
    'insight/stickiness': {
        icon: <IconStickiness />,
        iconColor: ['var(--color-insight-stickiness-light)'],
    },
    'insight/hog': {
        icon: <IconHogQL />,
        iconColor: ['var(--color-insight-sql-light)'],
    },
    team_activity: {
        icon: <IconNotification />,
        iconColor: ['var(--color-product-activity-light)', 'var(--color-product-activity-dark)'],
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
    [
        ...getTreeItemsNew(),
        {
            path: `Data/Source`,
            type: 'hog_function/source',
            href: urls.dataPipelinesNew('source'),
            icon: <IconPlug />,
            iconColor: ['var(--color-product-data-pipeline-light)'] as FileSystemIconColor,
        },
        {
            path: `Data/Destination`,
            type: 'hog_function/destination',
            href: urls.dataPipelinesNew('destination'),
            icon: <IconPlug />,
            iconColor: ['var(--color-product-data-pipeline-light)'] as FileSystemIconColor,
        },
        {
            path: `Data/Transformation`,
            type: 'hog_function/transformation',
            href: urls.dataPipelinesNew('transformation'),
            icon: <IconPlug />,
            iconColor: ['var(--color-product-data-pipeline-light)'] as FileSystemIconColor,
        },
        {
            path: `Data/Site app`,
            type: 'hog_function/site_app',
            href: urls.dataPipelinesNew('site_app'),
            icon: <IconPlug />,
            iconColor: ['var(--color-product-data-pipeline-light)'] as FileSystemIconColor,
        },
    ].sort((a, b) => a.path.localeCompare(b.path, undefined, { sensitivity: 'accent' }))

export const getDefaultTreeData = (): FileSystemImport[] => [
    ...getTreeItemsMetadata(),
    {
        path: 'Event definitions',
        category: 'Definitions',
        iconType: 'event_definition',
        href: urls.eventDefinitions(),
    },
    {
        path: 'Property definitions',
        category: 'Definitions',
        iconType: 'property_definition',
        href: urls.propertyDefinitions(),
    },
    {
        path: 'Annotations',
        category: 'Metadata',
        iconType: 'annotation',
        href: urls.annotations(),
    },
    {
        path: 'Comments',
        category: 'Metadata',
        iconType: 'comment',
        href: urls.comments(),
    },
    {
        path: 'Ingestion warnings',
        category: 'Pipeline',
        iconType: 'ingestion_warning',
        href: urls.ingestionWarnings(),
        flag: FEATURE_FLAGS.INGESTION_WARNINGS_ENABLED,
    },
    {
        path: `Sources`,
        category: 'Pipeline',
        type: 'hog_function/source',
        iconType: 'data_pipeline_metadata',
        href: urls.dataPipelines('sources'),
    } as FileSystemImport,
    {
        path: `Transformations`,
        category: 'Pipeline',
        type: 'hog_function/transformation',
        iconType: 'data_pipeline_metadata',
        href: urls.dataPipelines('transformations'),
    } as FileSystemImport,
    {
        path: `Destinations`,
        category: 'Pipeline',
        type: 'hog_function/destination',
        iconType: 'data_pipeline_metadata',
        href: urls.dataPipelines('destinations'),
    } as FileSystemImport,
]

export const getDefaultTreeProducts = (): FileSystemImport[] =>
    [
        ...getTreeItemsProducts(),
        {
            path: 'Dashboards',
            category: 'Analytics',
            type: 'dashboard',
            iconType: 'dashboard' as FileSystemIconType,
            iconColor: ['var(--color-product-dashboards-light)'] as FileSystemIconColor,
            href: urls.dashboards(),
        },
        {
            path: 'Notebooks',
            category: 'Tools',
            type: 'notebook',
            iconType: 'notebook' as FileSystemIconType,
            href: urls.notebooks(),
        },
        {
            path: `Data pipelines`,
            category: 'Tools',
            type: 'hog_function',
            iconType: 'data_pipeline' as FileSystemIconType,
            iconColor: ['var(--color-product-data-pipeline-light)'] as FileSystemIconColor,
            href: urls.dataPipelines(),
        } as FileSystemImport,
        {
            path: `SQL editor`,
            category: 'Analytics',
            type: 'sql',
            iconType: 'sql_editor' as FileSystemIconType,
            iconColor: ['var(--color-product-data-warehouse-light)'] as FileSystemIconColor,
            href: urls.sqlEditor(),
        } as FileSystemImport,
        {
            path: 'Heatmaps',
            category: 'Unreleased',
            iconType: 'heatmap' as FileSystemIconType,
            iconColor: [
                'var(--color-product-heatmaps-light)',
                'var(--color-product-heatmaps-dark)',
            ] as FileSystemIconColor,
            href: urls.heatmaps(),
            flag: FEATURE_FLAGS.HEATMAPS_UI,
            tags: ['alpha'],
        } as FileSystemImport,
    ].sort((a, b) => {
        if (a.visualOrder === -1) {
            return -1
        }
        if (b.visualOrder === -1) {
            return 1
        }
        return (a.visualOrder ?? 0) - (b.visualOrder ?? 0)
    })

export const getDefaultTreeGames = (): FileSystemImport[] =>
    [...getTreeItemsGames()].sort((a, b) => a.path.localeCompare(b.path, undefined, { sensitivity: 'accent' }))

export const getDefaultTreePersons = (): FileSystemImport[] => [
    {
        path: 'Persons',
        category: 'People',
        iconType: 'person' as FileSystemIconType,
        href: urls.persons(),
        visualOrder: 10,
    },
    {
        path: 'Cohorts',
        category: 'People',
        type: 'cohort' as FileSystemIconType,
        href: urls.cohorts(),
        visualOrder: 20,
    },
]
