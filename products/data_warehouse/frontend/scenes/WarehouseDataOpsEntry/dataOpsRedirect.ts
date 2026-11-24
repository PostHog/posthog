import { urls } from 'scenes/urls'

/** Where `/data-ops` goes when the console is on. Each Data ops tab has a new home. */
export function dataOpsRedirectTarget(searchParams: Record<string, unknown>): string {
    switch (searchParams.tab) {
        case 'monitoring':
            return `${urls.warehouseQueries()}?tab=performance`
        case 'settings':
            return urls.warehouseSettings()
        default:
            return `${urls.warehouseStorage()}?tab=readiness`
    }
}
