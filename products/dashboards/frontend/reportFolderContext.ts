import { FileSystemEntry } from '~/queries/schema/schema-general'

export interface ReportFolderContext {
    team_folder: boolean
    description: string
    pinned_dashboard_id: number | null
}

/** Folder context belongs to the folder, so everyone in the project sees the same starting point. */
export function getReportFolderContext(entry?: FileSystemEntry): ReportFolderContext {
    const context = entry?.meta?.custom_dashboards
    return {
        team_folder: context?.team_folder === true,
        description: typeof context?.description === 'string' ? context.description : '',
        pinned_dashboard_id:
            Number.isSafeInteger(context?.pinned_dashboard_id) && context.pinned_dashboard_id > 0
                ? context.pinned_dashboard_id
                : null,
    }
}
