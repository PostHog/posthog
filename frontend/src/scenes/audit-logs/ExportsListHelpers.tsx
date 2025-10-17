import { LemonTag } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

import { AdvancedActivityLogFilters, ExportedAsset } from './advancedActivityLogsLogic'

export const getStatusTag = (exportAsset: ExportedAsset): JSX.Element => {
    if (exportAsset.exception) {
        return <LemonTag type="danger">Failed</LemonTag>
    }
    if (exportAsset.has_content) {
        return <LemonTag type="success">Completed</LemonTag>
    }
    return <LemonTag type="default">Processing</LemonTag>
}

export const getHumanReadableFormat = (format: string): string => {
    const lowerFormat = format.toLowerCase()

    const csvMatchers = ['csv', 'text/csv']
    if (csvMatchers.some((matcher) => lowerFormat.includes(matcher))) {
        return 'CSV'
    }
    const excelMatchers = ['xlsx', 'excel', 'spreadsheet']
    if (excelMatchers.some((matcher) => lowerFormat.includes(matcher))) {
        return 'Excel'
    }

    return format.toUpperCase()
}

export const getFilterSummary = (exportAsset: ExportedAsset): string => {
    const filters = exportAsset.export_context?.filters as AdvancedActivityLogFilters
    if (!filters) {
        return 'No filters'
    }

    const activeFilters: string[] = []
    if (filters.start_date || filters.end_date) {
        activeFilters.push(`Date: 1`)
    }
    if (filters.users && filters.users.length > 0) {
        activeFilters.push(`Users: ${filters.users.length}`)
    }
    if (filters.scopes && filters.scopes.length > 0) {
        activeFilters.push(`Scopes: ${filters.scopes.length}`)
    }
    if (filters.activities && filters.activities.length > 0) {
        activeFilters.push(`Activities: ${filters.activities.length}`)
    }
    if (filters.detail_filters && Object.keys(filters.detail_filters).length > 0) {
        activeFilters.push(`Detail filters: ${Object.keys(filters.detail_filters).length}`)
    }
    if (filters.was_impersonated !== undefined) {
        activeFilters.push(`Was impersonated: ${filters.was_impersonated ? 'Yes' : 'No'}`)
    }
    if (filters.is_system !== undefined) {
        activeFilters.push(`Is system: ${filters.is_system ? 'Yes' : 'No'}`)
    }
    if (filters.item_ids && filters.item_ids.length > 0) {
        activeFilters.push(`Item IDs: ${filters.item_ids.length}`)
    }

    return activeFilters.length > 0 ? activeFilters.join(', ') : 'No filters'
}

export const getFilterTooltip = (exportAsset: ExportedAsset): JSX.Element => {
    const filters = exportAsset.export_context?.filters as AdvancedActivityLogFilters
    if (!filters) {
        return <div>No filters applied</div>
    }

    const filterSections: JSX.Element[] = []

    if (filters.start_date || filters.end_date) {
        const formatDate = (dateStr: string) => {
            try {
                return dayjs(dateStr).format('YYYY-MM-DD HH:mm:ss')
            } catch {
                return dateStr
            }
        }

        filterSections.push(
            <div key="dates">
                <strong>Date range:</strong>
                <br />
                {filters.start_date && `From: ${formatDate(filters.start_date)}`}
                {filters.start_date && filters.end_date && <br />}
                {filters.end_date && `To: ${formatDate(filters.end_date)}`}
            </div>
        )
    }

    if (filters.users && filters.users.length > 0) {
        filterSections.push(
            <div key="users">
                <strong>Users ({filters.users.length}):</strong>
                <br />
                {filters.users.slice(0, 5).join(', ')}
                {filters.users.length > 5 && `... and ${filters.users.length - 5} more`}
            </div>
        )
    }

    if (filters.scopes && filters.scopes.length > 0) {
        filterSections.push(
            <div key="scopes">
                <strong>Scopes ({filters.scopes.length}):</strong>
                <br />
                {filters.scopes.slice(0, 5).join(', ')}
                {filters.scopes.length > 5 && `... and ${filters.scopes.length - 5} more`}
            </div>
        )
    }

    if (filters.activities && filters.activities.length > 0) {
        filterSections.push(
            <div key="activities">
                <strong>Activities ({filters.activities.length}):</strong>
                <br />
                {filters.activities.slice(0, 5).join(', ')}
                {filters.activities.length > 5 && `... and ${filters.activities.length - 5} more`}
            </div>
        )
    }

    if (filters.detail_filters && Object.keys(filters.detail_filters).length > 0) {
        const detailFilterEntries = Object.entries(filters.detail_filters)
        const detailFilterText = detailFilterEntries.map(([field, filter]) => {
            const valueText = Array.isArray(filter.value) ? filter.value.join(', ') : filter.value
            const operationText =
                filter.operation === 'exact' ? 'equals' : filter.operation === 'contains' ? 'contains' : 'is one of'
            return `${field} ${operationText} "${valueText}"`
        })

        filterSections.push(
            <div key="detail_filters">
                <strong>Detail filters ({detailFilterEntries.length}):</strong>
                <br />
                {detailFilterText.slice(0, 3).join(', ')}
                {detailFilterText.length > 3 && `... and ${detailFilterText.length - 3} more`}
            </div>
        )
    }

    if (filters.was_impersonated !== undefined) {
        filterSections.push(
            <div key="was_impersonated">
                <strong>Was impersonated:</strong>
                <br />
                {filters.was_impersonated ? 'Yes' : 'No'}
            </div>
        )
    }

    if (filters.is_system !== undefined) {
        filterSections.push(
            <div key="is_system">
                <strong>Is system activity:</strong>
                <br />
                {filters.is_system ? 'Yes' : 'No'}
            </div>
        )
    }

    if (filters.item_ids && filters.item_ids.length > 0) {
        filterSections.push(
            <div key="item_ids">
                <strong>Item IDs ({filters.item_ids.length}):</strong>
                <br />
                {filters.item_ids.slice(0, 5).join(', ')}
                {filters.item_ids.length > 5 && `... and ${filters.item_ids.length - 5} more`}
            </div>
        )
    }

    if (filterSections.length === 0) {
        return <div>No filters applied</div>
    }

    return (
        <div className="space-y-2">
            {filterSections.map((section, index) => (
                <div key={index}>{section}</div>
            ))}
        </div>
    )
}

export const downloadExport = (exportAsset: ExportedAsset): void => {
    const link = document.createElement('a')
    link.href = `/api/environments/@current/exports/${exportAsset.id}/content/?download=true`
    link.download = exportAsset.filename || ''
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
}
