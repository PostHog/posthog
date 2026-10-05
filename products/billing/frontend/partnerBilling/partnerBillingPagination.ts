import type { PaginationManual } from '@posthog/lemon-ui'

export const PARTNER_BILLING_PAGE_SIZE = 20

export function partnerBillingPageParams(page: number): { limit: number; offset: number } {
    return { limit: PARTNER_BILLING_PAGE_SIZE, offset: (page - 1) * PARTNER_BILLING_PAGE_SIZE }
}

// An empty list has no count to page against, so LemonTable would offer a next page of nothing.
export function partnerBillingTablePagination(
    page: number,
    count: number | undefined,
    setPage: (page: number) => void
): PaginationManual | undefined {
    return count
        ? {
              controlled: true,
              pageSize: PARTNER_BILLING_PAGE_SIZE,
              currentPage: page,
              entryCount: count,
              onForward: () => setPage(page + 1),
              onBackward: () => setPage(page - 1),
          }
        : undefined
}
