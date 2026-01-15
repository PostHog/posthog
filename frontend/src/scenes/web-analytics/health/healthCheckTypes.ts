export type HealthCheckStatus = 'success' | 'warning' | 'error' | 'loading'

export type HealthCheckCategory = 'events' | 'configuration' | 'performance'

export interface HealthCheckAction {
    label: string
    onClick?: () => void
    to?: string
}

export interface HealthCheck {
    id: HealthCheckId
    category: HealthCheckCategory
    title: string
    description: string
    status: HealthCheckStatus
    action?: HealthCheckAction
    docsUrl?: string
    urgent?: boolean
}

export interface OverallHealthStatus {
    status: HealthCheckStatus
    summary: string
    passedCount: number
    warningCount: number
    errorCount: number
    totalCount: number
}

export enum HealthCheckId {
    PAGEVIEW_EVENTS = 'pageview_events',
    PAGELEAVE_EVENTS = 'pageleave_events',
    SCROLL_DEPTH = 'scroll_depth',

    AUTHORIZED_URLS = 'authorized_urls',
    REVERSE_PROXY = 'reverse_proxy',

    WEB_VITALS = 'web_vitals',
}
