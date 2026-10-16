const EXAMPLE_SOURCES: Record<string, string> = {
    GoogleAds: 'google',
    MetaAds: 'facebook',
    LinkedinAds: 'linkedin',
    TikTokAds: 'tiktok',
    RedditAds: 'reddit',
    BingAds: 'bing',
    SnapchatAds: 'snapchat',
}

export function SourceEventExample({ integration }: { integration: string | null }): JSX.Element | null {
    const source = integration ? EXAMPLE_SOURCES[integration] : undefined
    if (!source) {
        return null
    }
    return (
        <p className="text-xs text-secondary mb-0 mt-1">
            Illustrative event: <code>$pageview</code> with <code>utm_source={source}</code> and{' '}
            <code>utm_medium=cpc</code>. This example is not a captured event.
        </p>
    )
}
