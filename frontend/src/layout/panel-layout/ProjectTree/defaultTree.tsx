import {
    IconAI,
    IconApp,
    IconApps,
    IconBook,
    IconBug,
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
import { FEATURE_FLAGS } from 'lib/constants'
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
import { PipelineStage } from '~/types'

const iconTypes: Record<string, { icon: JSX.Element; iconColor?: [string, string] }> = {
    ai: {
        icon: <IconAI />,
        iconColor: ['var(--product-max-ai-primary)', 'var(--product-max-ai-primary)'],
    },
    cursorClick: {
        icon: <IconApp />,
        iconColor: ['var(--product-heatmaps-primary)', 'var(--product-heatmaps-primary)'],
    },
    database: {
        icon: <IconDatabase />,
        iconColor: ['var(--product-data-warehouse-primary)', 'var(--product-data-warehouse-primary)'],
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
        iconColor: ['var(--product-logs-primary)', 'var(--product-logs-primary)'],
    },
    notification: {
        icon: <IconNotification />,
        iconColor: ['var(--product-notification-primary)', 'var(--product-notification-primary)'],
    },
    pieChart: {
        icon: <IconPieChart />,
        iconColor: ['var(--product-web-analytics-primary)', 'var(--product-web-analytics-primary)'],
    },
    piggyBank: {
        icon: <IconPiggyBank />,
        iconColor: ['var(--product-revenue-analytics-primary)', 'var(--product-revenue-analytics-primary)'],
    },
    plug: {
        icon: <IconPlug />,
        iconColor: ['var(--product-data-pipeline-primary)', 'var(--product-data-pipeline-primary)'],
    },
    sql: {
        icon: <IconServer />,
        iconColor: ['var(--product-data-warehouse-primary)', 'var(--product-data-warehouse-primary)'],
    },
    warning: {
        icon: <IconWarning />,
    },
    bug: {
        icon: <IconBug />,
        iconColor: ['var(--product-error-tracking-primary)', 'var(--product-error-tracking-primary)'],
    },
}

const getIconColor = (type?: string): [string, string] => {
    const colorValue = (fileSystemTypes as unknown as Record<string, { iconColor?: string[] }>)[
        type as keyof typeof fileSystemTypes
    ]?.iconColor

    if (type && type in iconTypes) {
        return iconTypes[type].iconColor || ['currentColor', 'currentColor']
    }

    if (!colorValue) {
        return ['currentColor', 'currentColor']
    }

    // If no dark color, use light color
    if (colorValue.length === 1) {
        return [colorValue[0], colorValue[0]]
    }

    return [colorValue[0], colorValue[1]]
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
        iconType: 'warning',
        href: urls.ingestionWarnings(),
        flag: FEATURE_FLAGS.INGESTION_WARNINGS_ENABLED,
    },
]

export const getDefaultTreeProducts = (): FileSystemImport[] =>
    [
        ...getTreeItemsProducts(),
        {
            path: `AI chat`,
            type: 'aichat',
            href: urls.max(),
            flag: FEATURE_FLAGS.ARTIFICIAL_HOG,
        },
        {
            path: `Data pipelines`,
            type: 'hog_function',
            iconType: 'plug',
            href: urls.pipeline(),
        },
        {
            path: `SQL editor`,
            type: 'sql',
            href: urls.sqlEditor(),
        },
        {
            path: 'Data warehouse',
            iconType: 'database',
            href: urls.sqlEditor(),
        },
        {
            path: 'Error tracking',
            iconType: 'bug',
            href: urls.errorTracking(),
        },
        {
            path: 'Heatmaps',
            iconType: 'cursorClick',
            href: urls.heatmaps(),
            flag: FEATURE_FLAGS.HEATMAPS_UI,
        },
    ].sort((a, b) => a.path.localeCompare(b.path, undefined, { sensitivity: 'accent' }))

export const getDefaultTreeGames = (): FileSystemImport[] =>
    [...getTreeItemsGames()].sort((a, b) => a.path.localeCompare(b.path, undefined, { sensitivity: 'accent' }))
