import { IconCollapse, IconGear } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonInputSelect, LemonSkeleton, Spinner, Tooltip } from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { AuthorizedUrlList } from 'lib/components/AuthorizedUrlList/AuthorizedUrlList'
import { appEditorUrl, AuthorizedUrlListType } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { HeatmapsSettings } from 'lib/components/heatmaps/HeatMapsSettings'
import { DetectiveHog } from 'lib/components/hedgehogs'
import { heatmapDateOptions } from 'lib/components/IframedToolbarBrowser/utils'
import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { IconChevronRight, IconOpenInNew } from 'lib/lemon-ui/icons'
import React, { useEffect, useRef } from 'react'
import { teamLogic } from 'scenes/teamLogic'

import { sidePanelSettingsLogic } from '~/layout/navigation-3000/sidepanel/panels/sidePanelSettingsLogic'

import { heatmapsBrowserLogic } from './heatmapsBrowserLogic'

function UrlSearchHeader(): JSX.Element {
    const logic = heatmapsBrowserLogic()

    const { browserUrlSearchOptions, browserUrl } = useValues(logic)
    const { setBrowserSearch, setBrowserUrl } = useActions(logic)

    const placeholderUrl = browserUrlSearchOptions?.[0] ?? 'https://your-website.com/pricing'

    return (
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
    )
}

function HeatmapsBrowserIntro(): JSX.Element {
    const logic = heatmapsBrowserLogic()

    const { topUrls, topUrlsLoading, noPageviews } = useValues(logic)

    const { setBrowserUrl } = useActions(logic)

    return (
        <div className="flex-1 flex flex-col items-center justify-center overflow-y-auto">
            <div className="max-w-[50rem] py-6 px-3 h-full w-full">
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

function ForbiddenURL(): JSX.Element {
    const logic = heatmapsBrowserLogic()

    const { browserUrl } = useValues(logic)

    return (
        <div className="flex-1 p-4 gap-y-4">
            <LemonBanner type="error">
                {browserUrl} is not an authorized URL. Please add it to the list of authorized URLs to view heatmaps on
                this page.
            </LemonBanner>

            <h2>Authorized Toolbar URLs</h2>
            <AuthorizedUrlList type={AuthorizedUrlListType.TOOLBAR_URLS} />
        </div>
    )
}

function FilterPanel(): JSX.Element {
    const logic = heatmapsBrowserLogic()

    const {
        heatmapFilters,
        heatmapColorPalette,
        heatmapFixedPositionMode,
        viewportRange,
        commonFilters,
        filterPanelCollapsed,
    } = useValues(logic)
    const {
        patchHeatmapFilters,
        setHeatmapColorPalette,
        setHeatmapFixedPositionMode,
        setCommonFilters,
        toggleFilterPanelCollapsed,
    } = useActions(logic)

    return (
        <div className="flex flex-col gap-y-2 px-2 py-1 border-r w-100">
            {filterPanelCollapsed ? (
                <Tooltip title="Expand heatmap settings">
                    <LemonButton
                        size="small"
                        icon={<IconChevronRight />}
                        onClick={() => toggleFilterPanelCollapsed()}
                    />
                </Tooltip>
            ) : (
                <>
                    <div className="flex flex-row items-center">
                        <Tooltip title="Collapse heatmap settings">
                            <LemonButton
                                size="small"
                                icon={<IconCollapse className="rotate-90" />}
                                onClick={() => toggleFilterPanelCollapsed()}
                            />
                        </Tooltip>
                        <h2 className="flex-1 mb-0 px-2">Heatmap settings</h2>
                    </div>
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
                </>
            )}
        </div>
    )
}

function IframeErrorOverlay(): JSX.Element | null {
    const logic = heatmapsBrowserLogic()
    const { iframeBanner } = useValues(logic)
    return iframeBanner ? (
        <div className="absolute flex flex-col w-full h-full bg-blend-overlay items-start py-4 px-8 pointer-events-none">
            <LemonBanner className="w-full" type={iframeBanner.level}>
                {iframeBanner.message}. Your site might not allow being embedded in an iframe. You can click "Open in
                toolbar" above to visit your site and view the heatmap there.
            </LemonBanner>
        </div>
    ) : null
}

function LoadingOverlay(): JSX.Element | null {
    const logic = heatmapsBrowserLogic()
    const { loading } = useValues(logic)
    return loading ? (
        <div className="absolute flex flex-col w-full h-full items-center justify-center pointer-events-none">
            <Spinner className="text-5xl" textColored={true} />
        </div>
    ) : null
}

function EmbeddedHeatmapBrowser({
    iframeRef,
}: {
    iframeRef?: React.MutableRefObject<HTMLIFrameElement | null>
}): JSX.Element | null {
    const logic = heatmapsBrowserLogic()

    const { browserUrl } = useValues(logic)
    const { onIframeLoad, setIframeWidth } = useActions(logic)

    const { width: iframeWidth } = useResizeObserver<HTMLIFrameElement>({ ref: iframeRef })
    useEffect(() => {
        setIframeWidth(iframeWidth ?? null)
    }, [iframeWidth])

    return browserUrl ? (
        <div className="flex flex-row gap-x-2 w-full">
            <FilterPanel />
            <div className="relative flex-1 w-full h-full">
                <IframeErrorOverlay />
                <LoadingOverlay />
                <iframe
                    ref={iframeRef}
                    className="w-full h-full"
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
            </div>
        </div>
    ) : null
}

function Warnings(): JSX.Element | null {
    const { currentTeam } = useValues(teamLogic)
    const heatmapsEnabled = currentTeam?.heatmaps_opt_in

    const { openSettingsPanel } = useActions(sidePanelSettingsLogic)

    return !heatmapsEnabled ? (
        <LemonBanner
            type="warning"
            action={{
                type: 'secondary',
                icon: <IconGear />,
                onClick: () => openSettingsPanel({ settingId: 'heatmaps' }),
                children: 'Configure',
            }}
            dismissKey="heatmaps-might-be-disabled-warning"
        >
            You aren't collecting heatmaps data. Enable heatmaps in your project.
        </LemonBanner>
    ) : null
}

export function HeatmapsBrowser(): JSX.Element {
    const iframeRef = useRef<HTMLIFrameElement | null>(null)

    const logicProps = { ref: iframeRef }

    const logic = heatmapsBrowserLogic({ iframeRef })

    const { browserUrl, isBrowserUrlAuthorized } = useValues(logic)

    return (
        <BindLogic logic={heatmapsBrowserLogic} props={logicProps}>
            <div className="flex flex-col gap-2">
                <Warnings />
                <div className="flex flex-col overflow-hidden w-full h-[90vh] rounded border">
                    <UrlSearchHeader />

                    <div className="relative flex flex-1 bg-accent-3000 overflow-hidden">
                        {browserUrl ? (
                            <>
                                {!isBrowserUrlAuthorized ? (
                                    <ForbiddenURL />
                                ) : (
                                    <EmbeddedHeatmapBrowser iframeRef={iframeRef} />
                                )}
                            </>
                        ) : (
                            <HeatmapsBrowserIntro />
                        )}
                    </div>
                </div>
            </div>
        </BindLogic>
    )
}
