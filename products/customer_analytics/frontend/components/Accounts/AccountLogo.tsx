import { useValues } from 'kea'
import { useState } from 'react'

import { Lettermark } from 'lib/lemon-ui/Lettermark'
import { hashCodeForString } from 'lib/utils/strings'
import { projectLogic } from 'scenes/projectLogic'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

export function accountIconUrl(projectId: number, domain: string, theme: 'light' | 'dark'): string {
    return `/api/projects/${projectId}/accounts/icon/?domain=${encodeURIComponent(domain)}&theme=${theme}`
}

// Favicons the cache_account_domain_favicons Dagster job stores on our static CDN, shared with web analytics.
export function accountFaviconUrl(domain: string): string | null {
    return window.JS_URL ? `${window.JS_URL}/favicons/${encodeURIComponent(domain)}` : null
}

interface AccountLogoProps {
    domain?: string | null
    name: string
}

export function AccountLogo({ domain, name }: AccountLogoProps): JSX.Element {
    const { isDarkModeOn } = useValues(themeLogic)
    const { currentProjectId } = useValues(projectLogic)
    const theme = isDarkModeOn ? 'dark' : 'light'
    const iconKey = `${domain}|${theme}`
    const [failure, setFailure] = useState<{ iconKey: string; count: number } | null>(null)

    if (!domain || currentProjectId === null) {
        return <Lettermark name={name} index={hashCodeForString(name)} />
    }
    // The CDN copy first, so the logo.dev proxy and its budgets only serve domains the job has not cached yet.
    const sources = [accountFaviconUrl(domain), accountIconUrl(currentProjectId, domain, theme)].filter(
        (source): source is string => source !== null
    )
    const failedCount = failure?.iconKey === iconKey ? failure.count : 0
    if (failedCount >= sources.length) {
        return <Lettermark name={name} index={hashCodeForString(name)} />
    }
    return (
        <img
            key={sources[failedCount]}
            src={sources[failedCount]}
            alt=""
            className="size-6 shrink-0 rounded-sm object-contain"
            loading="lazy"
            onError={() => setFailure({ iconKey, count: failedCount + 1 })}
        />
    )
}
