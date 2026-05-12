import { EnvironmentLabelColor } from '~/types'

export interface EnvironmentLabelColorOption {
    key: EnvironmentLabelColor
    name: string
    /** Tailwind classes that paint a subtle colored pill that reads well in both themes. */
    pillClassName: string
    /** Solid dot used inline when we only want a hint of color (e.g. inside dropdown rows). */
    dotClassName: string
}

export const ENVIRONMENT_LABEL_COLORS: EnvironmentLabelColorOption[] = [
    {
        key: 'red',
        name: 'Red',
        pillClassName: 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-200',
        dotClassName: 'bg-red-500',
    },
    {
        key: 'orange',
        name: 'Orange',
        pillClassName: 'bg-orange-100 text-orange-700 dark:bg-orange-900/40 dark:text-orange-200',
        dotClassName: 'bg-orange-500',
    },
    {
        key: 'yellow',
        name: 'Yellow',
        pillClassName: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/40 dark:text-yellow-200',
        dotClassName: 'bg-yellow-500',
    },
    {
        key: 'green',
        name: 'Green',
        pillClassName: 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-200',
        dotClassName: 'bg-green-500',
    },
    {
        key: 'blue',
        name: 'Blue',
        pillClassName: 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-200',
        dotClassName: 'bg-blue-500',
    },
    {
        key: 'purple',
        name: 'Purple',
        pillClassName: 'bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-200',
        dotClassName: 'bg-purple-500',
    },
    {
        key: 'pink',
        name: 'Pink',
        pillClassName: 'bg-pink-100 text-pink-700 dark:bg-pink-900/40 dark:text-pink-200',
        dotClassName: 'bg-pink-500',
    },
    {
        key: 'gray',
        name: 'Gray',
        pillClassName: 'bg-gray-200 text-gray-700 dark:bg-gray-700 dark:text-gray-200',
        dotClassName: 'bg-gray-500',
    },
]

export const ENVIRONMENT_LABEL_COLOR_BY_KEY: Record<EnvironmentLabelColor, EnvironmentLabelColorOption> =
    ENVIRONMENT_LABEL_COLORS.reduce(
        (acc, color) => {
            acc[color.key] = color
            return acc
        },
        {} as Record<EnvironmentLabelColor, EnvironmentLabelColorOption>
    )

export const DEFAULT_ENVIRONMENT_LABEL_COLOR: EnvironmentLabelColor = 'gray'

export interface EnvironmentLabelTemplate {
    label: string
    color: EnvironmentLabelColor
    /** Short helper that explains when each template is the right pick. */
    description: string
}

/** Curated set of one-click presets. Users can still type a custom label after applying one. */
export const ENVIRONMENT_LABEL_TEMPLATES: EnvironmentLabelTemplate[] = [
    { label: 'Production', color: 'red', description: 'Real customer traffic — handle with care' },
    { label: 'Staging', color: 'orange', description: 'Pre-production, mirrors prod data shape' },
    { label: 'Development', color: 'blue', description: 'For day-to-day engineering work' },
    { label: 'Testing', color: 'purple', description: 'Automated tests or QA environments' },
    { label: 'Demo', color: 'green', description: 'Shown to prospects or in sales calls' },
    { label: 'Local', color: 'gray', description: 'Developer machine or sandbox' },
]
