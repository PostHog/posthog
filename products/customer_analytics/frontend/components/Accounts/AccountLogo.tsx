import { useValues } from 'kea'
import { useState } from 'react'

import { Lettermark } from 'lib/lemon-ui/Lettermark'
import { hashCodeForString } from 'lib/utils/strings'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

export function accountIconUrl(domain: string, theme: 'light' | 'dark'): string {
    return `/api/projects/@current/accounts/icon/?domain=${encodeURIComponent(domain)}&theme=${theme}`
}

interface AccountLogoProps {
    domain?: string | null
    name: string
}

export function AccountLogo({ domain, name }: AccountLogoProps): JSX.Element {
    const { isDarkModeOn } = useValues(themeLogic)
    const theme = isDarkModeOn ? 'dark' : 'light'
    const iconKey = `${domain}|${theme}`
    const [failedIconKey, setFailedIconKey] = useState<string | null>(null)

    if (!domain || failedIconKey === iconKey) {
        return <Lettermark name={name} index={hashCodeForString(name)} />
    }
    return (
        <img
            src={accountIconUrl(domain, theme)}
            alt=""
            className="size-6 shrink-0 rounded-sm object-contain"
            loading="lazy"
            onError={() => setFailedIconKey(iconKey)}
        />
    )
}
