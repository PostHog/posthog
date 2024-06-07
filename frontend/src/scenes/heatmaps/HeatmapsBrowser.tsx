import { LemonBanner, LemonButton, LemonInputSelect, LemonSkeleton, SpinnerOverlay } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { AuthorizedUrlList } from 'lib/components/AuthorizedUrlList/AuthorizedUrlList'
import { appEditorUrl, AuthorizedUrlListType } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { HeatmapsSettings } from 'lib/components/heatmaps/HeatMapsSettings'
import { heatmapDateOptions } from 'lib/components/heatmaps/utils'
import { DetectiveHog } from 'lib/components/hedgehogs'
import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { useEffect, useRef } from 'react'

import { heatmapsBrowserLogic } from './heatmapsBrowserLogic'

export function HeatmapsBrowser(): JSX.Element {
    const iframeRef = useRef<HTMLIFrameElement | null>(null)

    const { width: iframeWidth } = useResizeObserver<HTMLIFrameElement>({ ref: iframeRef })

    const logic = heatmapsBrowserLogic({ iframeRef })

    const {
        heatmapFilters,
        browserUrlSearchOptions,
        browserUrl,
        loading,
        isBrowserUrlAuthorized,
        heatmapColorPalette,
        heatmapFixedPositionMode,
        viewportRange,
        commonFilters,
    } = useValues(logic)
    const {
        setBrowserSearch,
        setBrowserUrl,
        onIframeLoad,
        patchHeatmapFilters,
        setHeatmapColorPalette,
        setHeatmapFixedPositionMode,
        setCommonFilters,
        setIframeWidth,
    } = useActions(logic)

    useEffect(() => {
        setIframeWidth(iframeWidth ?? null)
    }, [iframeWidth])

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
                                <div className="flex-1 p-4 gap-y-4">
                                    <LemonBanner type="error">
                                        {browserUrl} is not an authorized URL. Please add it to the list of authorized
                                        URLs to view heatmaps on this page.
                                    </LemonBanner>

                                    <h2>Authorized Toolbar URLs</h2>
                                    <AuthorizedUrlList type={AuthorizedUrlListType.TOOLBAR_URLS} />
                                </div>
                            ) : (
                                <div className="flex flex-row gap-x-2 w-full">
                                    <div className="flex flex-col gap-y-2 px-2 py-1">
                                        <DateFilter
                                            dateFrom={commonFilters.date_from}
                                            dateTo={commonFilters.date_to}
                                            onChange={(fromDate, toDate) => {
                                                setCommonFilters({ date_from: fromDate, date_to: toDate })
                                            }}
                                            dateOptions={heatmapDateOptions}
                                        />
                                        <HeatmapsSettings
                                            heatmapFilters={heatmapFilters}
                                            patchHeatmapFilters={patchHeatmapFilters}
                                            viewportRange={viewportRange}
                                            heatmapColorPalette={heatmapColorPalette}
                                            setHeatmapColorPalette={setHeatmapColorPalette}
                                            heatmapFixedPositionMode={heatmapFixedPositionMode}
                                            setHeatmapFixedPositionMode={setHeatmapFixedPositionMode}
                                        />
                                    </div>
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
                                        // these two sandbox values are necessary so that the site and toolbar can run
                                        // this is a very loose sandbox,
                                        // but we specify it so that at least other capabilities are denied
                                        sandbox="allow-scripts allow-same-origin"
                                        // we don't allow things such as camera access though
                                        allow=""
                                    />

                                    {loading && <SpinnerOverlay />}
                                </div>
                            )}
                        </>
                    ) : (
                        <HeatmapsBrowserIntro />
                    )}
                </div>
            </div>
        </div>
    )
}

function HeatmapsBrowserIntro(): JSX.Element {
    // the heatmaps browserLogic is not keyed on its props, so we can reference it here
    // without passing them around
    const logic = heatmapsBrowserLogic()

    const { topUrls, topUrlsLoading, noPageviews } = useValues(logic)

    const { setBrowserUrl } = useActions(logic)

    return (
        <div className="flex-1 flex items-center justify-center overflow-y-auto">
            <div className="max-w-[50rem] my-6 mx-3">
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
                            You can also view heatmaps for any page on your website by entering the URL above. As long
                            as the page has the PostHog Toolbar installed, and can be loaded in an iframe, you can view
                            heatmaps for it.
                        </p>
                    </div>
                </div>

                <div className="gap-y-px p-2 border bg-bg-light rounded">
                    {topUrlsLoading ? (
                        <LemonSkeleton className="h-10" repeat={10} />
                    ) : noPageviews ? (
                        <LemonBanner type="info">
                            No pageview events have been received yet. Once you have some data, you'll see the most
                            viewed pages here.
                        </LemonBanner>
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
    )
}
