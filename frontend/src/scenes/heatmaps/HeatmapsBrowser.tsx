import { LemonBanner, LemonButton, LemonInputSelect, LemonSkeleton, SpinnerOverlay } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { AuthorizedUrlList } from 'lib/components/AuthorizedUrlList/AuthorizedUrlList'
import { appEditorUrl, AuthorizedUrlListType } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { DetectiveHog } from 'lib/components/hedgehogs'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { useRef } from 'react'

import { heatmapsBrowserLogic } from './heatmapsBrowserLogic'

export function HeatmapsBrowser(): JSX.Element {
    const iframeRef = useRef<HTMLIFrameElement | null>(null)
    const logic = heatmapsBrowserLogic({ iframeRef })

    const { browserUrlSearchOptions, browserUrl, loading, isBrowserUrlAuthorized, topUrls, topUrlsLoading } =
        useValues(logic)
    const { setBrowserSearch, setBrowserUrl, onIframeLoad } = useActions(logic)

    const placeholderUrl = browserUrlSearchOptions?.[0] ?? 'https://your-website.com/pricing'

    return (
        <div className="flex flex-wrap gap-2">
            <div className="flex flex-col overflow-hidden w-full h-[90vh] rounded border">
                <div className="bg-accent-3000 p-2 border-b flex items-center gap-2">
                    <span className="flex-1">
                        <LemonInputSelect
                            mode="single"
                            allowCustomValues
                            placeholder={`e.g. ${placeholderUrl}`}
                            onInputChange={(e) => setBrowserSearch(e)}
                            value={browserUrl ? [browserUrl] : undefined}
                            onChange={(v) => setBrowserUrl(v[0] ?? null)}
                            options={
                                browserUrlSearchOptions?.map((x) => ({
                                    label: x,
                                    key: x,
                                })) ?? []
                            }
                        />
                    </span>

                    <LemonButton
                        type="secondary"
                        sideIcon={<IconOpenInNew />}
                        to={
                            browserUrl
                                ? appEditorUrl(browserUrl, {
                                      userIntent: 'heatmaps',
                                  })
                                : undefined
                        }
                        targetBlank
                        disabledReason={!browserUrl ? 'Select a URL first' : undefined}
                    >
                        Open in toolbar
                    </LemonButton>
                </div>

                <div className="relative flex flex-1 bg-accent-3000 overflow-hidden">
                    {browserUrl ? (
                        <>
                            {!isBrowserUrlAuthorized ? (
                                <div className="flex-1 p-4 space-y-4">
                                    <LemonBanner type="error">
                                        {browserUrl} is not an authorized URL. Please add it to the list of authorized
                                        URLs to view heatmaps on this page.
                                    </LemonBanner>

                                    <h2>Authorized Toolbar URLs</h2>
                                    <AuthorizedUrlList type={AuthorizedUrlListType.TOOLBAR_URLS} />
                                </div>
                            ) : (
                                <>
                                    <iframe
                                        ref={iframeRef}
                                        className="flex-1"
                                        src={appEditorUrl(browserUrl, {
                                            userIntent: 'heatmaps',
                                        })}
                                        // eslint-disable-next-line react/forbid-dom-props
                                        style={{
                                            background: '#FFF',
                                        }}
                                        onLoad={onIframeLoad}
                                    />

                                    {loading && <SpinnerOverlay />}
                                </>
                            )}
                        </>
                    ) : (
                        <div className="flex-1 flex items-center justify-center overflow-y-auto">
                            <div className="max-w-[50rem] m-6">
                                <div className="flex items-center flex-wrap gap-6 my-10">
                                    <div className="w-50">
                                        <DetectiveHog className="w-full h-full" />
                                    </div>

                                    <div className="flex-1">
                                        <h2>Welcome to Heatmaps</h2>
                                        <p>
                                            Heatmaps are powered by the embedded JavaScript SDK and allow you to see a
                                            range of user interactions directly on your website via the Toolbar.
                                        </p>
                                        <p>
                                            You can also view heatmaps for any page on your website by entering the URL
                                            above. As long as the page has the PostHog Toolbar installed, and can be
                                            loaded in an iframe, you can view heatmaps for it.
                                        </p>
                                    </div>
                                </div>

                                <div className="space-y-px p-2 border bg-bg-light rounded">
                                    {topUrlsLoading ? (
                                        <LemonSkeleton className="h-10" repeat={10} />
                                    ) : (
                                        <>
                                            {topUrls?.map(({ url }) => (
                                                <LemonButton key={url} fullWidth onClick={() => setBrowserUrl(url)}>
                                                    {url}
                                                </LemonButton>
                                            ))}
                                        </>
                                    )}
                                </div>
                            </div>
                        </div>
                    )}
                </div>
            </div>
        </div>
    )
}
