import type { ReactNode } from 'react'

import { IconPlug } from '@posthog/icons'

import { fileSystemTypes } from '~/products'
import { FileSystemType } from '~/types'

import { iconForType } from './defaultTree'

export interface ProjectTreeProductType {
    value: string
    label: string
    icon?: ReactNode
    flag?: string
}

const missingProductTypes: ProjectTreeProductType[] = [
    { value: 'destination', label: 'Destinations', icon: <IconPlug /> },
    { value: 'site_app', label: 'Site apps', icon: <IconPlug /> },
    { value: 'source', label: 'Sources', icon: <IconPlug /> },
    { value: 'transformation', label: 'Transformations', icon: <IconPlug /> },
]

export const getProjectTreeProductTypes = (): ProjectTreeProductType[] => [
    ...Object.entries(fileSystemTypes as unknown as Record<string, FileSystemType>).map(
        ([key, value]): ProjectTreeProductType => ({
            value: value.filterKey || key,
            label: value.name,
            icon: iconForType(value.iconType),
            flag: value.flag,
        })
    ),
    ...missingProductTypes,
]
