import type { ComponentType } from 'react'

import {
    IconBrackets,
    IconCalculator,
    IconCalendar,
    IconCheck,
    IconClock,
    IconCode,
    IconCode2,
    IconDatabase,
} from '@posthog/icons'

import { IconTextSize } from 'lib/lemon-ui/icons'

import { DatabaseSerializedFieldType } from '~/queries/schema/schema-general'

type IconComponent = ComponentType<{ className?: string }>

/** The icon a column row shows for its type. The Lemon tree tints it, the quill tree keeps it muted. */
export function getFieldTypeIconComponent(fieldType?: DatabaseSerializedFieldType): IconComponent | null {
    if (!fieldType) {
        return null
    }
    switch (fieldType) {
        case 'string':
            return IconTextSize
        case 'integer':
        case 'float':
        case 'decimal':
            return IconCalculator
        case 'boolean':
            return IconCheck
        case 'datetime':
            return IconClock
        case 'date':
            return IconCalendar
        case 'array':
        case 'json':
            return IconBrackets
        case 'expression':
            return IconCode
        case 'view':
        case 'materialized_view':
        case 'lazy_table':
        case 'virtual_table':
            return IconDatabase
        default:
            return IconCode2
    }
}

export const getFieldTypeIconClassName = (fieldType: DatabaseSerializedFieldType): string => {
    switch (fieldType) {
        case 'string':
            return 'text-sky-500'
        case 'integer':
        case 'float':
        case 'decimal':
            return 'text-emerald-500'
        case 'boolean':
            return 'text-purple-500'
        case 'datetime':
            return 'text-amber-500'
        case 'date':
            return 'text-orange-500'
        case 'array':
        case 'json':
            return 'text-teal-500'
        case 'expression':
        case 'field_traverser':
            return 'text-slate-500'
        case 'view':
        case 'materialized_view':
        case 'lazy_table':
        case 'virtual_table':
            return 'text-blue-500'
        default:
            return 'text-tertiary'
    }
}
