import { slugify } from 'lib/utils/strings'

import type { DashboardV2SpecApi } from '../generated/api.schemas'

const UID_MAX_LENGTH = 63

export function dashboardUid(title: string, suffix?: string): string {
    const tail = suffix ? `-${suffix}` : ''
    const slug = slugify(title)
        .replace(/^[^a-z0-9]+/, '')
        .slice(0, UID_MAX_LENGTH - tail.length)
    return `${slug.length >= 2 ? slug : 'dashboard'}${tail}`
}

export function blankDashboardSpec(title: string, uidSuffix?: string): DashboardV2SpecApi {
    return {
        uid: dashboardUid(title, uidSuffix),
        title,
        time: { from: 'now-7d', to: 'now' },
        variables: [],
        layout: { type: 'grid', columns: 24, items: [] },
        panels: {},
    }
}
