import React, { CSSProperties } from 'react'

import {
    IconAI,
    IconApp,
    IconApps,
    IconBook,
    IconChevronRight,
    IconCursor,
    IconDashboard,
    IconDatabase,
    IconFunnels,
    IconGraph,
    IconHandMoney,
    IconHogQL,
    IconLifecycle,
    IconLive,
    IconNotebook,
    IconNotification,
    IconPeople,
    IconPieChart,
    IconPiggyBank,
    IconPlug,
    IconRetention,
    IconServer,
    IconStickiness,
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
import { FileSystemIconColor, PipelineStage, PipelineTab } from '~/types'

const iconTypes: Record<FileSystemIconType, { icon: JSX.Element; iconColor?: FileSystemIconColor }> = {
    ai: {
        icon: <IconAI />,
        iconColor: ['var(--color-product-max-ai-light)'],
    },
    cursor: {
        icon: <IconCursor />,
    },
    heatmap: {
        icon: <IconApp />,
        iconColor: ['var(--color-product-heatmaps-light)', 'var(--color-product-heatmaps-dark)'],
    },
    database: {
        icon: <IconDatabase />,
        iconColor: ['var(--color-product-data-warehouse-light)'],
    },
    definitions: {
        icon: <IconApps />,
    },
    folder: {
        icon: <IconChevronRight />,
    },
    handMoney: {
        icon: <IconHandMoney />,
    },
    live: {
        icon: <IconLive />,
        iconColor: ['var(--color-product-logs-light)'],
    },
    notification: {
        icon: <IconNotification />,
        iconColor: ['var(--product-notification-light)'],
    },
    pieChart: {
        icon: <IconPieChart />,
        iconColor: ['var(--color-product-web-analytics-light)', 'var(--color-product-web-analytics-dark)'],
    },
    piggyBank: {
        icon: <IconPiggyBank />,
        iconColor: ['var(--color-product-revenue-analytics-light)', 'var(--color-product-revenue-analytics-dark)'],
    },
    plug: {
        icon: <IconPlug />,
        iconColor: ['var(--color-product-data-pipeline-light)'],
    },
    sql: {
        icon: <IconServer />,
        iconColor: ['var(--color-product-data-warehouse-light)'],
    },
    warning: {
        icon: <IconWarning />,
    },
    errorTracking: {
        icon: <IconWarning />,
        iconColor: ['var(--color-product-error-tracking-light)', 'var(--color-product-error-tracking-dark)'],
    },
    insightFunnel: {
        icon: <IconFunnels />,
        iconColor: ['var(--color-insight-funnel-light)'],
    },
    insightTrends: {
        icon: <IconTrends />,
        iconColor: ['var(--color-insight-trends-light)'],
    },
    insightRetention: {
        icon: <IconRetention />,
        iconColor: ['var(--color-insight-retention-light)'],
    },
    insightUserPaths: {
        icon: <IconUserPaths />,
        iconColor: ['var(--color-insight-user-paths-light)', 'var(--color-user-paths-dark)'],
    },
    insightLifecycle: {
        icon: <IconLifecycle />,
        iconColor: ['var(--color-insight-lifecycle-light)'],
    },
    insightStickiness: {
        icon: <IconStickiness />,
        iconColor: ['var(--color-insight-stickiness-light)'],
    },
    insightHogQL: {
        icon: <IconHogQL />,
        iconColor: ['var(--color-insight-sql-light)'],
    },
    cohort: {
        icon: <IconPeople />,
    },
    insight: {
        icon: <IconGraph />,
        iconColor: ['var(--color-product-product-analytics-light)'],
    },
}

const getIconColor = (type?: string, colorOverride?: FileSystemIconColor): FileSystemIconColor => {
    // Get the official icon color
    const iconTypeColor = type && iconTypes[type as keyof typeof iconTypes]?.iconColor

    // fallback: Get the file system color
    const fileSystemColor = (fileSystemTypes as unknown as Record<string, { iconColor?: FileSystemIconColor }>)[
        type as keyof typeof fileSystemTypes
    ]?.iconColor

    // If we have a color override, use it
    // Otherwise, use the official icon color, then the file system color and finally if all else is undefined use the inherited default color
    const color = colorOverride ?? iconTypeColor ?? fileSystemColor ?? ['currentColor', 'currentColor']
    return color.length === 1 ? [color[0], color[0]] : (color as FileSystemIconColor)
}

type ProductIconWrapperProps = {
    type?: string
    children: React.ReactNode
    // Light and dark color overrides
    colorOverride?: FileSystemIconColor
}

export const ProductIconWrapper = ({ type, children, colorOverride }: ProductIconWrapperProps): JSX.Element => {
    const [lightColor, darkColor] = getIconColor(type, colorOverride)

    // By default icons will not be colorful, to add color, wrap the icon with the class: "group/colorful-product-icons colorful-product-icons-true"
    return (
        <span
            className="flex items-center group-[.colorful-product-icons-true]/colorful-product-icons:text-[var(--product-icon-color-light)] dark:group-[.colorful-product-icons-true]/colorful-product-icons:text-[var(--product-icon-color-dark)]"
            // eslint-disable-next-line react/forbid-dom-props
            style={
                (colorOverride
                    ? { '--product-icon-color-light': colorOverride[0], '--product-icon-color-dark': colorOverride[1] }
                    : {
                          '--product-icon-color-light': lightColor,
                          '--product-icon-color-dark': darkColor,
                      }) as CSSProperties
            }
        >
            {children}
        </span>
    )
}

export function iconForType(type?: string, colorOverride?: FileSystemIconColor): JSX.Element {
    if (!type) {
        return (
            <ProductIconWrapper type={type} colorOverride={colorOverride}>
                <IconBook />
            </ProductIconWrapper>
        )
    }

    // Then check fileSystemTypes
    if (type in fileSystemTypes && fileSystemTypes[type as keyof typeof fileSystemTypes]?.icon) {
        const IconElement = fileSystemTypes[type as keyof typeof fileSystemTypes].icon
        return (
            <ProductIconWrapper type={type} colorOverride={colorOverride}>
                {IconElement}
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
            href: urls.pipelineNodeNew(PipelineStage.Source),
            icon: <IconPlug />,
            iconColor: ['var(--color-product-data-pipeline-light)'] as FileSystemIconColor,
        },
        {
            path: `Data/Destination`,
            type: 'hog_function/destination',
            href: urls.pipelineNodeNew(PipelineStage.Destination),
            icon: <IconPlug />,
            iconColor: ['var(--color-product-data-pipeline-light)'] as FileSystemIconColor,
        },
        {
            path: `Data/Transformation`,
            type: 'hog_function/transformation',
            href: urls.pipelineNodeNew(PipelineStage.Transformation),
            icon: <IconPlug />,
            iconColor: ['var(--color-product-data-pipeline-light)'] as FileSystemIconColor,
        },
        {
            path: `Data/Site app`,
            type: 'hog_function/site_app',
            href: urls.pipelineNodeNew(PipelineStage.SiteApp),
            icon: <IconPlug />,
            iconColor: ['var(--color-product-data-pipeline-light)'] as FileSystemIconColor,
        },
    ].sort((a, b) => a.path.localeCompare(b.path, undefined, { sensitivity: 'accent' }))

export const getDefaultTreeData = (): FileSystemImport[] => [
    ...getTreeItemsMetadata(),
    {
        path: 'Event definitions',
        category: 'Definitions',
        icon: <IconApps />,
        href: urls.eventDefinitions(),
    },
    {
        path: 'Property definitions',
        category: 'Definitions',
        icon: <IconApps />,
        href: urls.propertyDefinitions(),
    },
    {
        path: 'Annotations',
        category: 'Metadata',
        icon: <IconNotification />,
        href: urls.annotations(),
    },
    {
        path: 'Comments',
        category: 'Metadata',
        icon: <IconNotification />,
        href: urls.comments(),
    },
    {
        path: 'Ingestion warnings',
        category: 'Pipeline',
        icon: <IconWarning />,
        href: urls.ingestionWarnings(),
        flag: FEATURE_FLAGS.INGESTION_WARNINGS_ENABLED,
    },
    {
        path: `Sources`,
        category: 'Pipeline',
        type: 'hog_function/source',
        icon: <IconPlug />,
        href: urls.pipeline(PipelineTab.Sources),
    } as FileSystemImport,
    {
        path: `Transformations`,
        category: 'Pipeline',
        type: 'hog_function/transformation',
        icon: <IconPlug />,
        href: urls.pipeline(PipelineTab.Transformations),
    } as FileSystemImport,
    {
        path: `Destinations`,
        category: 'Pipeline',
        type: 'hog_function/destination',
        icon: <IconPlug />,
        href: urls.pipeline(PipelineTab.Destinations),
    } as FileSystemImport,
]

export const getDefaultTreeProducts = (): FileSystemImport[] =>
    [
        ...getTreeItemsProducts(),
        {
            path: 'Dashboards',
            category: 'Analytics',
            type: 'dashboard',
            icon: <IconDashboard />,
            iconColor: ['var(--color-product-dashboards-light)'] as FileSystemIconColor,
            href: urls.dashboards(),
        },
        {
            path: 'Notebooks',
            category: 'Tools',
            type: 'notebook',
            icon: <IconNotebook />,
            href: urls.notebooks(),
        },
        {
            path: `Data pipelines`,
            category: 'Tools',
            type: 'hog_function',
            icon: <IconPlug />,
            iconColor: ['var(--color-product-data-pipeline-light)'] as FileSystemIconColor,
            href: urls.pipeline(),
        } as FileSystemImport,
        {
            path: `SQL editor`,
            category: 'Analytics',
            type: 'sql',
            icon: <IconDatabase />,
            iconColor: ['var(--color-product-data-warehouse-light)'] as FileSystemIconColor,
            href: urls.sqlEditor(),
        } as FileSystemImport,
        {
            path: 'Heatmaps',
            category: 'Behavior',
            icon: <IconApp />,
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
        icon: <IconPeople />,
        href: urls.persons(),
        visualOrder: 10,
    },
    {
        path: 'Cohorts',
        category: 'People',
        type: 'cohort',
        href: urls.cohorts(),
        visualOrder: 20,
    },
]
