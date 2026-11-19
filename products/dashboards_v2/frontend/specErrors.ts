import type { DashboardV2InvalidSpecErrorApi } from './generated/api.schemas'

export function specErrorMessages(error: unknown, fallback: string): string[] {
    const data = (error as { data?: Partial<DashboardV2InvalidSpecErrorApi> } | null)?.data
    const issues = data?.extra?.issues
    if (issues?.length) {
        return issues.map((issue) => `${issue.path}: ${issue.message}`)
    }
    return [data?.detail || fallback]
}
