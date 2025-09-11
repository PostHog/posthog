import { LemonTag } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

import { ExportedAsset } from './advancedActivityLogsLogic'

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
    const filters = exportAsset.export_context?.filters
    if (!filters) {
        return 'No filters'
    }

    const activeFilters: string[] = []
    if (filters.start_date || filters.end_date) {
        activeFilters.push(`Date filter: 1`)
    }
    if (filters.users && filters.users.length > 0) {
        activeFilters.push(`Users: ${filters.users.length}`)
    }
    if (filters.scopes && filters.scopes.length > 0) {
        activeFilters.push(`Scopes: ${filters.scopes.length}`)
    }
    if (filters.activities && filters.activities.length > 0) {
        activeFilters.push(`Actions: ${filters.activities.length}`)
    }

    return activeFilters.length > 0 ? activeFilters.join(', ') : 'No filters'
}

export const getFilterTooltip = (exportAsset: ExportedAsset): JSX.Element => {
    const filters = exportAsset.export_context?.filters
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
                <strong>Date Range:</strong>
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
                <strong>Actions ({filters.activities.length}):</strong>
                <br />
                {filters.activities.slice(0, 5).join(', ')}
                {filters.activities.length > 5 && `... and ${filters.activities.length - 5} more`}
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
