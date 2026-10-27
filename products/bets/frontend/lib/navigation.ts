import { urls } from 'scenes/urls'

import type { Breadcrumb } from '~/types'

export function betsBreadcrumbs(
    page: 'overview' | 'all' | 'new' | 'detail' | 'edit' | 'settings',
    bet?: { id: string; title: string }
): Breadcrumb[] {
    const root: Breadcrumb = { key: 'bets', name: 'Bets', path: urls.bets() }
    const all: Breadcrumb = { key: 'bets-all', name: 'All bets', path: urls.betsAll() }
    if (page === 'overview') {
        return [root, { key: 'bets-overview', name: 'Overview' }]
    }
    if (page === 'settings') {
        return [root, { key: 'bets-settings', name: 'Settings' }]
    }
    if (page === 'all') {
        return [root, all]
    }
    if (page === 'new') {
        return [root, all, { key: 'bets-new', name: 'New bet' }]
    }
    const detail: Breadcrumb = { key: bet?.id ?? 'bet', name: bet?.title || 'Bet', path: bet && urls.bet(bet.id) }
    return page === 'edit' ? [root, all, detail, { key: 'bet-edit', name: 'Edit' }] : [root, all, detail]
}
