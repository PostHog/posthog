// @ts-nocheck
// Test cases for the url-naming rules. Semgrep ignores `paths:` in test mode, so the urls.ts rule
// also sees the manifest-shaped lines here.

export const manifest = {
    routes: {
        // ruleid: frontend-route-hyphen, frontend-url-hyphen
        '/visual_review': ['VisualReviewIndex', 'visualReviewIndex'],
        // ruleid: frontend-route-hyphen, frontend-url-hyphen
        '/visual-review/repos/:repoId/snapshot_overview': ['VisualReviewSnapshotOverview', 'overview'],
        // ok: frontend-route-hyphen
        '/visual-review/repos/:repo_id/runs': ['VisualReviewRuns', 'visualReviewRepoRuns'],
        // ok: frontend-route-hyphen
        '/data-management/*': ['DataManagement', 'dataManagement'],
    },
    redirects: {
        // A redirect keeps an old path alive on purpose, so only the generic urls.ts rule fires here.
        // ruleid: frontend-url-hyphen
        '/user_interviews': '/user-research',
    },
}

export const urls = {
    // ruleid: frontend-url-hyphen
    deadLetterQueue: (): string => '/instance/dead_letter_queue',
    // ruleid: frontend-url-hyphen
    productTour: (id: string): string => `/product_tours/${id}`,
    // ruleid: frontend-url-hyphen
    login2FASetup: (): string => '/login/2fa_setup',
    // ruleid: frontend-url-hyphen
    savedView: (id: string): string => `/items/${id}/saved_view`,
    // ok: frontend-url-hyphen
    savedViewHyphen: (item_id: string): string => `/items/${item_id}/saved-view`,
    // ok: frontend-url-hyphen
    hogFunction: (id: string, tab?: string): string => `/functions/${id}${tab ? `?tab=${tab}` : ''}`,
    // ok: frontend-url-hyphen
    featureFlagStaff: (teamId: string): string => `/feature-flags/staff?team_id=${teamId}`,
    // ok: frontend-url-hyphen
    insightAlert: (id: string, alertId: string): string => `/insights/${id}/alerts?alert_id=${alertId}`,
    // ok: frontend-url-hyphen
    dataManagement: (): string => '/data-management#section_one',
    // nosemgrep: frontend-url-hyphen
    verifyEmail: (): string => '/verify_email',
}

export const settings = [
    // ruleid: settings-id-hyphen
    { level: 'project', id: 'project_details', title: 'General' },
    // ok: settings-id-hyphen
    { level: 'project', id: 'project-details', title: 'General' },
]
