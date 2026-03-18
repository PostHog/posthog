import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { DetectiveHog } from 'lib/components/hedgehogs'
import { heatmapLogic } from 'scenes/heatmaps/scenes/heatmap/heatmapLogic'

import { heatmapsBrowserLogic } from './heatmapsBrowserLogic'

export function HeatmapsInfoBanner(): JSX.Element {
    return (
        <div className="flex items-center flex-wrap gap-6">
            <div className="w-50">
                <DetectiveHog className="w-full h-full" />
            </div>

            <div className="flex-1">
                <h2>Welcome to Heatmaps</h2>
                <p>
                    Heatmaps are powered by the embedded JavaScript SDK and allow you to see a range of user
                    interactions directly on your website via the Toolbar.
                </p>
                <p>
                    You can also view heatmaps for any page on your website by entering the URL above. As long as the
                    page has the PostHog Toolbar installed, and can be loaded in an iframe, you can view heatmaps for
                    it.
                </p>
            </div>
        </div>
    )
}

export function HeatmapsUrlsList(): JSX.Element {
    const { topUrls, topUrlsLoading, noPageviews } = useValues(heatmapsBrowserLogic)

    const { setDisplayUrl } = useActions(heatmapLogic)

    return (
        <div className="flex-1 flex items-center overflow-y-auto">
            <div className=" w-full">
                <div className="gap-y-px p-2 border bg-surface-primary rounded">
                    {topUrlsLoading ? (
                        <LemonSkeleton className="h-10" repeat={10} />
                    ) : noPageviews ? (
                        <LemonBanner type="info">
                            No pageview events have been received yet. Once you have some data, you'll see the most
                            viewed pages here.
                        </LemonBanner>
                    ) : (
                        <>
                            <span className="text-sm font-medium text-muted ml-2">Most viewed pages:</span>
                            {topUrls?.map(({ url }) => (
                                <LemonButton
                                    key={url}
                                    fullWidth
                                    onClick={() => {
                                        setDisplayUrl(url)
                                    }}
                                >
                                    {url}
                                </LemonButton>
                            ))}
                        </>
                    )}
                </div>
            </div>
        </div>
    )
}
