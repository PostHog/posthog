import { IconRefresh } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

function reloadWithFreshAssets(): void {
    // A plain reload() can be served the same cached page that referenced the now-missing
    // chunk. Navigating to a cache-busted URL forces the browser to fetch the current one.
    const url = new URL(window.location.href)
    url.searchParams.set('_reload', String(Date.now()))
    window.location.replace(url.toString())
}

export function ErrorNetwork(): JSX.Element {
    return (
        <div>
            <h1 className="mb-1 text-2xl font-bold">New version available</h1>
            <p>A new version of PostHog is available. Refresh the page to continue.</p>
            <p>
                <LemonButton type="primary" onClick={reloadWithFreshAssets} icon={<IconRefresh />}>
                    Refresh page
                </LemonButton>
            </p>
        </div>
    )
}
