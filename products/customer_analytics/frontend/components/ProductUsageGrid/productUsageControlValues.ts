import type { BookActivityInterval, DateRange } from '~/queries/schema/schema-general'

import type { ProductUsageSource, ProductUsageZoom } from './productUsageData'
import type { ProductUsageFilters } from './productUsageQueries'

export interface ProductUsageControls extends ProductUsageFilters {
    dateRange: DateRange
    interval: BookActivityInterval
    zoom: ProductUsageZoom
    grouping: string
    selected: string[]
    firstUse: boolean
    openProducts: string[]
}
export const DEFAULT_CONTROLS: ProductUsageControls = {
    search: '',
    assignedTo: [],
    assignmentStatus: 'all',
    relationshipId: null,
    dateRange: { date_from: '-7wStart', date_to: null },
    interval: 'week',
    zoom: 'products',
    grouping: 'role',
    selected: [],
    firstUse: false,
    openProducts: [],
}

export function parseProductUsageControls(raw: unknown, defaults: ProductUsageControls): ProductUsageControls {
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
        return defaults
    }
    const value = raw as Record<string, unknown>
    const range =
        value.dateRange && typeof value.dateRange === 'object' ? (value.dateRange as Record<string, unknown>) : {}
    const date = (value: unknown, fallback: string | null | undefined): string | null | undefined =>
        value === null || (typeof value === 'string' && value.length <= 100) ? value : fallback
    return {
        search: typeof value.search === 'string' ? value.search.slice(0, 200) : defaults.search,
        assignedTo: Array.isArray(value.assignedTo)
            ? value.assignedTo.filter((id): id is number => Number.isInteger(id) && id > 0).slice(0, 100)
            : defaults.assignedTo,
        assignmentStatus:
            value.assignmentStatus === 'assigned' || value.assignmentStatus === 'unassigned'
                ? value.assignmentStatus
                : 'all',
        relationshipId:
            typeof value.relationshipId === 'string' && value.relationshipId.length <= 100
                ? value.relationshipId
                : null,
        dateRange: {
            date_from: date(range.date_from, defaults.dateRange.date_from),
            date_to: date(range.date_to, defaults.dateRange.date_to),
        },
        interval:
            typeof value.interval === 'string' && ['day', 'week', 'month'].includes(value.interval)
                ? (value.interval as BookActivityInterval)
                : defaults.interval,
        zoom:
            value.zoom === 'count' || value.zoom === 'products' || value.zoom === 'users' ? value.zoom : defaults.zoom,
        grouping: value.grouping === 'usecase' ? 'usecase' : 'role',
        selected: Array.isArray(value.selected)
            ? value.selected
                  .filter((key): key is string => typeof key === 'string' && key.length > 0 && key.length <= 128)
                  .slice(0, 64)
            : [],
        firstUse: value.firstUse === true,
        openProducts: Array.isArray(value.openProducts)
            ? value.openProducts
                  .filter((key): key is string => typeof key === 'string' && key.length <= 256)
                  .slice(0, 50)
            : [],
    }
}

export function getProductUsageSourceKey(source: ProductUsageSource): string {
    return source.kind === 'hogql'
        ? JSON.stringify([
              source.kind,
              source.query,
              Object.entries(source.mapping)
                  .filter(([, value]) => value !== undefined)
                  .sort(([left], [right]) => left.localeCompare(right)),
          ])
        : source.kind
}
