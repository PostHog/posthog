import {
    IconAI,
    IconApp,
    IconApps,
    IconBook,
    IconCalendar,
    IconChevronRight,
    IconCursor,
    IconDatabase,
    IconFunnels,
    IconGraph,
    IconHandMoney,
    IconHogQL,
    IconLifecycle,
    IconLive,
    IconNotification,
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
import { IconCohort } from 'lib/lemon-ui/icons'
import React, { CSSProperties } from 'react'
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
        iconColor: ['var(--product-max-ai-light)'],
    },
    cursor: {
        icon: <IconCursor />,
    },
    heatmap: {
        icon: <IconApp />,
        iconColor: ['var(--product-heatmaps-light)', 'var(--product-heatmaps-dark)'],
    },
    database: {
        icon: <IconDatabase />,
        iconColor: ['var(--product-data-warehouse-light)'],
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
        iconColor: ['var(--product-logs-light)'],
    },
    notification: {
        icon: <IconNotification />,
        iconColor: ['var(--product-notification-light)'],
    },
    pieChart: {
        icon: <IconPieChart />,
        iconColor: ['var(--product-web-analytics-light)', 'var(--product-web-analytics-dark)'],
    },
    piggyBank: {
        icon: <IconPiggyBank />,
        iconColor: ['var(--product-revenue-analytics-light)', 'var(--product-revenue-analytics-dark)'],
    },
    plug: {
        icon: <IconPlug />,
        iconColor: ['var(--product-data-pipeline-light)'],
    },
    sql: {
        icon: <IconServer />,
        iconColor: ['var(--product-data-warehouse-light)'],
    },
    warning: {
        icon: <IconWarning />,
    },
    errorTracking: {
        icon: <IconWarning />,
        iconColor: ['var(--product-error-tracking-light)', 'var(--product-error-tracking-dark)'],
    },
    insightFunnel: {
        icon: <IconFunnels />,
        iconColor: ['var(--insight-funnel-light)'],
    },
    insightTrends: {
        icon: <IconTrends />,
        iconColor: ['var(--insight-trends-light)'],
    },
    insightRetention: {
        icon: <IconRetention />,
        iconColor: ['var(--insight-retention-light)'],
    },
    insightUserPaths: {
        icon: <IconUserPaths />,
        iconColor: ['var(--insight-user-paths-light)', 'var(--insight-user-paths-dark)'],
    },
    insightLifecycle: {
        icon: <IconLifecycle />,
        iconColor: ['var(--insight-lifecycle-light)'],
    },
    insightStickiness: {
        icon: <IconStickiness />,
        iconColor: ['var(--insight-stickiness-light)'],
    },
    insightHogQL: {
        icon: <IconHogQL />,
        iconColor: ['var(--insight-sql-light)'],
    },
    insightCalendarHeatmap: {
        icon: <IconCalendar className="mt-[2px]" />,
        iconColor: ['var(--insight-calendar-heatmap-light)', 'var(--insight-calendar-heatmap-dark)'],
    },
    cohort: {
        icon: <IconCohort />,
    },
    insight: {
        icon: <IconGraph />,
        iconColor: ['var(--product-product-analytics-light)'],
    },
}

const getIconColor = (type?: string): FileSystemIconColor => {
    const fileSystemColor = (fileSystemTypes as unknown as Record<string, { iconColor?: FileSystemIconColor }>)[
        type as keyof typeof fileSystemTypes
    ]?.iconColor

    const iconTypeColor = type && iconTypes[type as keyof typeof iconTypes]?.iconColor

    const color = iconTypeColor ?? fileSystemColor ?? ['currentColor']
    return color.length === 1 ? [color[0], color[0]] : (color as FileSystemIconColor)
}

const ProductIconWrapper = ({ type, children }: { type?: string; children: React.ReactNode }): JSX.Element => {
    const [lightColor, darkColor] = getIconColor(type)

    // By default icons will not be colorful, to add color, wrap the icon with the class: "group/colorful-product-icons colorful-product-icons-true"
    return (
        <span
            className="group-[.colorful-product-icons-true]/colorful-product-icons:text-[var(--product-icon-color-light)] dark:group-[.colorful-product-icons-true]/colorful-product-icons:text-[var(--product-icon-color-dark)]"
            // eslint-disable-next-line react/forbid-dom-props
            style={
                { '--product-icon-color-light': lightColor, '--product-icon-color-dark': darkColor } as CSSProperties
            }
        >
            {children}
        </span>
    )
}

export function iconForType(type?: string): JSX.Element {
    if (!type) {
        return (
            <ProductIconWrapper type={type}>
                <IconBook />
            </ProductIconWrapper>
        )
    }

    // Then check fileSystemTypes
    if (type in fileSystemTypes && fileSystemTypes[type as keyof typeof fileSystemTypes]?.icon) {
        const IconElement = fileSystemTypes[type as keyof typeof fileSystemTypes].icon
        return <ProductIconWrapper type={type}>{IconElement}</ProductIconWrapper>
    }

    if (type in iconTypes) {
        return <ProductIconWrapper type={type}>{iconTypes[type as keyof typeof iconTypes].icon}</ProductIconWrapper>
    }

    // Handle hog_function types
    if (type.startsWith('hog_function/')) {
        return (
            <ProductIconWrapper type="plug">
                <IconPlug />
            </ProductIconWrapper>
        )
    }

    // Default
    return (
        <ProductIconWrapper type={type}>
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
        },
        {
            path: `Data/Destination`,
            type: 'hog_function/destination',
            href: urls.pipelineNodeNew(PipelineStage.Destination),
        },
        {
            path: `Data/Transformation`,
            type: 'hog_function/transformation',
            href: urls.pipelineNodeNew(PipelineStage.Transformation),
        },
        {
            path: `Data/Site app`,
            type: 'hog_function/site_app',
            href: urls.pipelineNodeNew(PipelineStage.SiteApp),
        },
    ].sort((a, b) => a.path.localeCompare(b.path, undefined, { sensitivity: 'accent' }))

export const getDefaultTreeData = (): FileSystemImport[] => [
    ...getTreeItemsMetadata(),
    {
        path: 'Event definitions',
        category: 'Definitions',
        iconType: 'definitions',
        href: urls.eventDefinitions(),
    },
    {
        path: 'Property definitions',
        category: 'Definitions',
        iconType: 'definitions',
        href: urls.propertyDefinitions(),
    },
    {
        path: 'Annotations',
        category: 'Metadata',
        iconType: 'notification',
        href: urls.annotations(),
    },
    {
        path: 'Ingestion warnings',
        category: 'Pipeline',
        iconType: 'warning',
        href: urls.ingestionWarnings(),
        flag: FEATURE_FLAGS.INGESTION_WARNINGS_ENABLED,
    },
    {
        path: `Sources`,
        category: 'Pipeline',
        type: 'hog_function/source',
        iconType: 'plug',
        href: urls.pipeline(PipelineTab.Sources),
    } as FileSystemImport,
    {
        path: `Transformations`,
        category: 'Pipeline',
        type: 'hog_function/transformation',
        iconType: 'plug',
        href: urls.pipeline(PipelineTab.Transformations),
    } as FileSystemImport,
    {
        path: `Destinations`,
        category: 'Pipeline',
        type: 'hog_function/destination',
        iconType: 'plug',
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
            href: urls.dashboards(),
        },
        {
            path: 'Notebooks',
            category: 'Tools',
            type: 'notebook',
            href: urls.notebooks(),
        },
        {
            path: `Data pipelines`,
            category: 'Tools',
            type: 'hog_function',
            iconType: 'plug',
            href: urls.pipeline(),
        } as FileSystemImport,
        {
            path: `SQL editor`,
            category: 'Analytics',
            type: 'sql',
            href: urls.sqlEditor(),
        } as FileSystemImport,
        {
            path: 'Heatmaps',
            category: 'Behavior',
            iconType: 'heatmap',
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
        iconType: 'cohort',
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
