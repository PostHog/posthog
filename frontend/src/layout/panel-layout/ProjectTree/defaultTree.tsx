import {
    IconAI,
    IconApp,
    IconApps,
    IconBook,
    IconChevronRight,
    IconDatabase,
    IconHandMoney,
    IconLive,
    IconNotification,
    IconPieChart,
    IconPiggyBank,
    IconPlug,
    IconServer,
    IconWarning,
} from '@posthog/icons'
import { FEATURE_FLAGS, PRODUCT_VISUAL_ORDER } from 'lib/constants'
import React, { CSSProperties } from 'react'
import { urls } from 'scenes/urls'

import {
    fileSystemTypes,
    getTreeItemsDataManagement,
    getTreeItemsGames,
    getTreeItemsNew,
    getTreeItemsProducts,
} from '~/products'
import { FileSystemImport } from '~/queries/schema/schema-general'
import { FileSystemIconColor, PipelineStage } from '~/types'

const iconTypes: Record<string, { icon: JSX.Element; iconColor?: FileSystemIconColor }> = {
    ai: {
        icon: <IconAI />,
        iconColor: ['var(--product-max-ai-light)'],
    },
    cursorClick: {
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
        iconColor: ['var(--product-error-tracking-light)', 'var(--product-error-tracking-dark)'],
    },
    ingestionWarning: {
        icon: <IconWarning />,
    },
}

const getIconColor = (type?: string): FileSystemIconColor => {
    const fileSystemColor = (fileSystemTypes as unknown as Record<string, { iconColor?: FileSystemIconColor }>)[
        type as keyof typeof fileSystemTypes
    ]?.iconColor
    const iconTypeColor = type && iconTypes[type]?.iconColor

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
        return <ProductIconWrapper type={type}>{iconTypes[type].icon}</ProductIconWrapper>
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

export const getDefaultTreeDataManagement = (): FileSystemImport[] => [
    ...getTreeItemsDataManagement(),
    {
        path: 'Event definitions',
        iconType: 'definitions',
        href: urls.eventDefinitions(),
    },
    {
        path: 'Property definitions',
        iconType: 'definitions',
        href: urls.propertyDefinitions(),
    },
    {
        path: 'Annotations',
        iconType: 'notification',
        href: urls.annotations(),
    },
    {
        path: 'Ingestion warnings',
        iconType: 'ingestionWarning',
        href: urls.ingestionWarnings(),
        flag: FEATURE_FLAGS.INGESTION_WARNINGS_ENABLED,
    },
]

export const getDefaultTreeProducts = (): FileSystemImport[] =>
    [
        ...getTreeItemsProducts(),
        {
            path: `Max AI`,
            type: 'aichat',
            href: urls.max(),
            flag: FEATURE_FLAGS.ARTIFICIAL_HOG,
            visualOrder: PRODUCT_VISUAL_ORDER.aiChat,
        } as FileSystemImport,
        {
            path: `Data pipelines`,
            type: 'hog_function',
            iconType: 'plug',
            href: urls.pipeline(),
            visualOrder: PRODUCT_VISUAL_ORDER.dataPipeline,
        } as FileSystemImport,
        {
            path: `SQL editor`,
            type: 'sql',
            href: urls.sqlEditor(),
            visualOrder: PRODUCT_VISUAL_ORDER.sqlEditor,
        } as FileSystemImport,
        {
            path: 'Error tracking',
            iconType: 'warning',
            href: urls.errorTracking(),
            visualOrder: PRODUCT_VISUAL_ORDER.errorTracking,
        } as FileSystemImport,
        {
            path: 'Heatmaps',
            iconType: 'cursorClick',
            href: urls.heatmaps(),
            flag: FEATURE_FLAGS.HEATMAPS_UI,
            visualOrder: PRODUCT_VISUAL_ORDER.heatmaps,
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
        iconType: 'cohort',
        href: urls.persons(),
        visualOrder: 10,
    },
    {
        path: 'Cohorts',
        type: 'cohort',
        href: urls.cohorts(),
        visualOrder: 20,
    },
]
