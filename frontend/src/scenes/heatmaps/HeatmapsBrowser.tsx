import { IconGear, IconRevert } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonInput, LemonInputSelect, LemonSkeleton, Spinner } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import { AuthorizedUrlList } from 'lib/components/AuthorizedUrlList/AuthorizedUrlList'
import { appEditorUrl, AuthorizedUrlListType } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { DetectiveHog, FilmCameraHog } from 'lib/components/hedgehogs'
import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import React, { useEffect, useRef } from 'react'
import { FilterPanel } from 'scenes/heatmaps/FilterPanel'
import { FixedReplayHeatmapBrowser } from 'scenes/heatmaps/FixedReplayHeatmapBrowser'
import { teamLogic } from 'scenes/teamLogic'

import { sidePanelSettingsLogic } from '~/layout/navigation-3000/sidepanel/panels/sidePanelSettingsLogic'

import { heatmapsBrowserLogic } from './heatmapsBrowserLogic'

function UrlSearchHeader(): JSX.Element {
    const logic = heatmapsBrowserLogic()

    const { browserUrlSearchOptions, browserUrl, isBrowserUrlValid, replayIframeData, hasValidReplayIframeData } =
        useValues(logic)
    const { setBrowserSearch, setBrowserUrl, setReplayIframeData, setReplayIframeDataURL } = useActions(logic)

    const placeholderUrl = browserUrlSearchOptions?.[0] ?? 'https://your-website.com/pricing'

    return (
        <div className="bg-surface-primary p-2 border-b flex items-center gap-2">
            <span className="flex-1">
                {hasValidReplayIframeData ? (
                    <LemonInput value={replayIframeData?.url} onChange={(s) => setReplayIframeDataURL(s)} />
                ) : (
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
                        className={!isBrowserUrlValid ? 'border-red-500' : undefined}
                    />
                )}
            </span>
            {hasValidReplayIframeData ? (
                <LemonButton
                    icon={<IconRevert />}
                    onClick={() => {
                        setReplayIframeData(null)
                        setBrowserUrl(null)
                    }}
                >
                    Reset
                </LemonButton>
            ) : null}
            <LemonButton
                type="secondary"
                sideIcon={<IconOpenInNew />}
                to={
                    browserUrl
                        ? appEditorUrl(browserUrl, {
                              userIntent: 'heatmaps',
                          })
                        : hasValidReplayIframeData && replayIframeData?.url
                        ? appEditorUrl(replayIframeData?.url, {
                              userIntent: 'heatmaps',
                          })
                        : undefined
                }
                targetBlank
                disabledReason={!browserUrl && !hasValidReplayIframeData ? 'Select a URL first' : undefined}
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

function InvalidURL(): JSX.Element {
    return (
        <div className="flex-1 p-4 gap-y-4">
            <LemonBanner type="error">Not a valid URL. Can't load a heatmap for that 😰</LemonBanner>
        </div>
    )
}

function IframeErrorOverlay(): JSX.Element | null {
    const logic = heatmapsBrowserLogic()
    const { iframeBanner } = useValues(logic)
    return iframeBanner ? (
        <div className="absolute mt-10 flex flex-col w-full h-full bg-blend-overlay items-start py-4 px-8 pointer-events-none">
            <LemonBanner className="w-full" type={iframeBanner.level}>
                {iframeBanner.message}. Your site might not allow being embedded in an iframe. You can click "Open in
                toolbar" above to visit your site and view the heatmap there.
            </LemonBanner>
        </div>
    ) : null
}

function LoadingOverlay(): JSX.Element {
    return (
        <div className="absolute flex flex-col w-full h-full items-center justify-center pointer-events-none">
            <Spinner className="text-5xl" textColored={true} />
        </div>
    )
}

export function ViewportChooser({
    setWidth,
    selectedWidth,
}: {
    setWidth: (width: number | null) => void
    selectedWidth: number | null
}): JSX.Element {
    const [hoveredWidth, setHoveredWidth] = React.useState<number | null>(null)

    const viewports: Record<number, string> = {
        320: 'Mobile - S (320px)',
        375: 'Mobile - M (375px)',
        425: 'Mobile - L (425px)',
        768: 'Tablet (768px)',
        1024: 'Desktop (1024px)',
        1440: 'Desktop - L (1440px)',
        1920: 'Desktop - XL (1920px)',
    }

    const handleWidthSelect = (width: number): void => {
        setWidth(selectedWidth === width ? null : width)
    }

    const label =
        hoveredWidth !== null ? (
            <span>{viewports[hoveredWidth]}</span>
        ) : selectedWidth !== null ? (
            <span>{viewports[selectedWidth]}</span>
        ) : (
            <span>Choose viewport</span>
        )

    return (
        <div className="w-full flex flex-row items-center justify-center relative h-8 border-y rounded-0 bg-bg-light select-none overflow-hidden">
            {Object.keys(viewports)
                .map((width) => {
                    const numWidth = parseInt(width)
                    return (
                        <div
                            key={width}
                            className={clsx(
                                'absolute h-full border-l border-r cursor-pointer flex items-center justify-center px-2 text-xs transition-colors',
                                'hover:bg-primary hover:bg-opacity-20',
                                'left-1/2 -translate-x-1/2',
                                selectedWidth === numWidth && 'bg-primary bg-opacity-20'
                            )}
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{
                                width: numWidth,
                            }}
                            onClick={() => handleWidthSelect(numWidth)}
                            onMouseEnter={() => setHoveredWidth(numWidth)}
                            onMouseLeave={() => setHoveredWidth(null)}
                        >
                            {numWidth === 320 ? <span>{label}</span> : null}
                        </div>
                    )
                })
                .reverse()}
        </div>
    )
}

function EmbeddedHeatmapBrowser({
    iframeRef,
}: {
    iframeRef?: React.MutableRefObject<HTMLIFrameElement | null>
}): JSX.Element | null {
    const logic = heatmapsBrowserLogic()
    const [widthOverride, setWidthOverride] = React.useState<number | null>(null)

    const {
        browserUrl,
        loading,
        iframeBanner,
        heatmapFilters,
        heatmapColorPalette,
        heatmapFixedPositionMode,
        viewportRange,
        commonFilters,
        filterPanelCollapsed,
        heatmapEmpty,
    } = useValues(logic)
    const {
        onIframeLoad,
        setIframeWidth,
        patchHeatmapFilters,
        setHeatmapColorPalette,
        setHeatmapFixedPositionMode,
        setCommonFilters,
        toggleFilterPanelCollapsed,
    } = useActions(logic)

    const embeddedFilterPanelProps = {
        heatmapFilters,
        heatmapColorPalette,
        heatmapFixedPositionMode,
        viewportRange,
        commonFilters,
        filterPanelCollapsed,
        loading,
        patchHeatmapFilters,
        setHeatmapColorPalette,
        setHeatmapFixedPositionMode,
        setCommonFilters,
        toggleFilterPanelCollapsed,
    }

    const { width: iframeWidth } = useResizeObserver<HTMLIFrameElement>({ ref: iframeRef })
    useEffect(() => {
        if (widthOverride === null) {
            setIframeWidth(iframeWidth ?? null)
        }
    }, [iframeWidth, setIframeWidth, widthOverride])

    return browserUrl ? (
        <div className="flex flex-row gap-x-2 w-full">
            <FilterPanel {...embeddedFilterPanelProps} isEmpty={heatmapEmpty} />
            <div className="relative flex-1 w-full h-full border-l mt-2">
                {loading ? <LoadingOverlay /> : null}
                {!loading && iframeBanner ? <IframeErrorOverlay /> : null}
                <ViewportChooser setWidth={setWidthOverride} selectedWidth={widthOverride} />
                <div className="flex relative justify-center h-full">
                    <iframe
                        ref={iframeRef}
                        className="h-full bg-white"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ width: widthOverride ?? '100%' }}
                        src={appEditorUrl(browserUrl, {
                            userIntent: 'heatmaps',
                        })}
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
                onClick: () => openSettingsPanel({ sectionId: 'environment-autocapture', settingId: 'heatmaps' }),
                children: 'Configure',
            }}
            dismissKey="heatmaps-might-be-disabled-warning"
        >
            You aren't collecting heatmaps data. Enable heatmaps in your project.
        </LemonBanner>
    ) : null
}

function ReplayIframeDataIntro(): JSX.Element | null {
    const { hasValidReplayIframeData } = useValues(heatmapsBrowserLogic)

    return hasValidReplayIframeData ? (
        <LemonBanner type="info" dismissKey="heatmaps-replay-iframe-data-intro">
            <div className="flex flex-row gap-2 items-center">
                <FilmCameraHog className="w-30 h-30" />
                <div>
                    You're using session recording data as the background for this heatmap.{' '}
                    <p>You can change the URL that the heatmap data loads below, for example to add wildcards.</p>
                    And use the filters below to slice and dice the data.
                </div>
            </div>
        </LemonBanner>
    ) : null
}

export function HeatmapsBrowser(): JSX.Element {
    const iframeRef = useRef<HTMLIFrameElement | null>(null)

    const logicProps = { ref: iframeRef }

    const logic = heatmapsBrowserLogic({ iframeRef })

    const { browserUrl, isBrowserUrlAuthorized, hasValidReplayIframeData, isBrowserUrlValid } = useValues(logic)

    return (
        <BindLogic logic={heatmapsBrowserLogic} props={logicProps}>
            <div className="flex flex-col gap-2">
                <Warnings />
                <ReplayIframeDataIntro />
                <div className="flex flex-col overflow-hidden w-full h-[90vh] rounded border">
                    <UrlSearchHeader />

                    <div className="relative flex flex-1 overflow-hidden">
                        {hasValidReplayIframeData ? (
                            <FixedReplayHeatmapBrowser iframeRef={iframeRef} />
                        ) : browserUrl ? (
                            <>
                                {!isBrowserUrlAuthorized ? (
                                    <ForbiddenURL />
                                ) : !isBrowserUrlValid ? (
                                    <InvalidURL />
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
