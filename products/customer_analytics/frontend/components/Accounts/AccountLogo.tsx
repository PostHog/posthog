import { useValues } from 'kea'
import { useState } from 'react'

import { Lettermark } from 'lib/lemon-ui/Lettermark'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

export function accountIconUrl(domain: string, theme: 'light' | 'dark'): string {
    return `/api/projects/@current/accounts/icon/?domain=${encodeURIComponent(domain)}&theme=${theme}`
}

// Spreads names across the lettermark palette so neighboring rows rarely share a color, and picks
// the same one for a given account on every render.
function lettermarkIndex(name: string): number {
    let hash = 0
    for (let index = 0; index < name.length; index++) {
        hash = (hash * 31 + name.charCodeAt(index)) | 0
    }
    return Math.abs(hash)
}

interface AccountLogoProps {
    /** Bare hostname the backend resolved for this account. */
    domain?: string | null
    /** Account name, used for the lettermark when there's no logo to show. */
    name: string
}

/** The company's logo beside its name, falling back to a lettermark.
 *
 * Accounts without a domain and domains without a logo on file are both common, so the fallback
 * is a normal outcome rather than an error state — it keeps every row the same shape either way.
 */
export function AccountLogo({ domain, name }: AccountLogoProps): JSX.Element {
    const { isDarkModeOn } = useValues(themeLogic)
    // logo.dev picks the logo variant suited to the active background.
    const theme = isDarkModeOn ? 'dark' : 'light'
    // Failure latches per (domain, theme) — the unit the request URL varies over — so a failed
    // load in one theme doesn't blank the other, and a theme flip retries after a transient error
    // (cheap: definitive misses are cached server-side for a day).
    const iconKey = `${domain}|${theme}`
    const [failedIconKey, setFailedIconKey] = useState<string | null>(null)

    if (!domain || failedIconKey === iconKey) {
        return <Lettermark name={name} index={lettermarkIndex(name)} />
    }
    return (
        <img
            src={accountIconUrl(domain, theme)}
            alt=""
            // Sized and shaped to match the lettermark, so swapping between them shifts nothing.
            className="size-6 shrink-0 rounded-sm object-contain"
            loading="lazy"
            onError={() => setFailedIconKey(iconKey)}
        />
    )
}
