import { BindLogic, useActions, useValues } from 'kea'
import { useRef } from 'react'

import { HedgehogMagnifyingGlass } from '@posthog/brand/hoggies'
import { IconDownload, IconGear, IconRevert } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonDivider, LemonInput, LemonLabel, LemonSkeleton } from '@posthog/lemon-ui'

import { AuthorizedUrlList } from 'lib/components/AuthorizedUrlList/AuthorizedUrlList'
import { AuthorizedUrlListType, appEditorUrl } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { exportsLogic } from 'lib/components/ExportButton/exportsLogic'
import { heatmapDataLogic } from 'lib/components/heatmaps/heatmapDataLogic'
import { dayjs } from 'lib/dayjs'
import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { FixedReplayHeatmapBrowser } from 'scenes/heatmaps/components/FixedReplayHeatmapBrowser'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { FilterPanel } from './FilterPanel'
import { heatmapsBrowserLogic } from './heatmapsBrowserLogic'
import { IframeHeatmapBrowser } from './IframeHeatmapBrowser'
import { recordingClickmapLogic } from './recordingClickmapLogic'

function ExportButton({
    iframeRef,
}: {
    iframeRef?: React.MutableRefObject<HTMLIFrameElement | null>
}): JSX.Element | null {
    const logic = heatmapsBrowserLogic()

    const { dataUrl } = useValues(logic)
    const { startHeatmapExport } = useActions(exportsLogic)

    const { heatmapFilters, heatmapColorPalette, heatmapFixedPositionMode, commonFilters } = useValues(
        heatmapDataLogic({ context: 'in-app' })
    )

    const { width: iframeWidth, height: iframeHeight } = useResizeObserver<HTMLIFrameElement>({ ref: iframeRef })

    // Creating an export requires editor access to the export resource.
    const exportAccessControlDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.Export,
        AccessControlLevel.Editor
    )

    const handleExport = (): void => {
        if (dataUrl) {
            startHeatmapExport({
                heatmap_url: dataUrl,
                width: iframeWidth,
                height: iframeHeight,
                heatmap_color_palette: heatmapColorPalette,
                heatmap_fixed_position_mode: heatmapFixedPositionMode,
                common_filters: commonFilters,
                heatmap_filters: heatmapFilters,
                filename: `heatmap-${new URL(dataUrl).hostname}/${new URL(dataUrl).pathname.slice(1, 11)}-${dayjs().format('YYYY-MM-DD-HH-mm')}`,
            })
        }
    }

    return (
        <div className="flex justify-between items-center mt-2 md:mt-0">
            <LemonButton
                size="small"
                type="secondary"
                onClick={handleExport}
                icon={<IconDownload />}
                tooltip="Export heatmap as PNG"
                data-attr="export-heatmap"
                disabledReason={
                    (!dataUrl ? 'We can export only the URL with heatmaps' : undefined) ??
                    exportAccessControlDisabledReason ??
                    undefined
                }
            >
                Export
            </LemonButton>
        </div>
    )
}

function UrlSearchHeader({ iframeRef }: { iframeRef?: React.MutableRefObject<HTMLIFrameElement | null> }): JSX.Element {
    const {
        browserUrlSearchOptions,
        dataUrl,
        isBrowserUrlValid,
        replayIframeData,
        hasValidReplayIframeData,
        browserSearchTerm,
        displayUrl,
    } = useValues(heatmapsBrowserLogic)
    const { setBrowserSearch, setDataUrl, setReplayIframeData, setReplayIframeDataURL, setDisplayUrl } =
        useActions(heatmapsBrowserLogic)

    const placeholderUrl = browserUrlSearchOptions?.[0] ?? 'https://your-website.com/pricing'

    return (
        <>
            <div className="flex-none md:flex justify-between items-end gap-2 w-full">
                <div className="flex gap-2 flex-1 min-w-0">
                    <div className="flex-1">
                        {hasValidReplayIframeData ? (
                            <>
                                <LemonLabel>Display URL</LemonLabel>
                                <div className="text-xs text-muted mb-1">
                                    You're using session recording data as the background for this heatmap.
                                </div>
                                <div className="mt-2">
                                    <LemonLabel>Heatmap data URL</LemonLabel>
                                    <div className="text-xs text-muted mb-1">
                                        Same as display URL by default - add * for wildcards to aggregate data from
                                        multiple pages
                                    </div>
                                    <LemonInput
                                        value={replayIframeData?.url}
                                        onChange={(s) => setReplayIframeDataURL(s)}
                                        className="truncate"
                                        size="small"
                                    />
                                </div>
                            </>
                        ) : (
                            <>
                                <div className="relative">
                                    <LemonLabel>Display URL</LemonLabel>
                                    <div className="text-xs text-muted mb-1">
                                        Enter a working URL from your site for iframe preview
                                    </div>
                                    <div className="flex gap-2">
                                        <LemonInput
                                            size="small"
                                            placeholder={`e.g. ${placeholderUrl}`}
                                            value={displayUrl || browserSearchTerm || ''}
                                            onChange={(value) => {
                                                setBrowserSearch(value)
                                                setDisplayUrl(value || null)
                                            }}
                                            onKeyDown={(e) => {
                                                if (e.key === 'Enter' && browserSearchTerm) {
                                                    setDisplayUrl(browserSearchTerm)
                                                }
                                            }}
                                            className="truncate flex-1"
                                        />
                                        <LemonButton
                                            type="secondary"
                                            icon={<IconOpenInNew />}
                                            to={
                                                displayUrl || dataUrl
                                                    ? appEditorUrl(displayUrl || dataUrl || '', {
                                                          userIntent: 'heatmaps',
                                                      })
                                                    : hasValidReplayIframeData && replayIframeData?.url
                                                      ? appEditorUrl(replayIframeData?.url, {
                                                            userIntent: 'heatmaps',
                                                        })
                                                      : undefined
                                            }
                                            targetBlank
                                            disabledReason={
                                                !displayUrl && !dataUrl && !hasValidReplayIframeData
                                                    ? 'Select a URL first'
                                                    : undefined
                                            }
                                            size="small"
                                            data-attr="heatmaps-open-in-toolbar"
                                        >
                                            Open in toolbar
                                        </LemonButton>
                                    </div>
                                    {/* Show suggestions when there are options and user has typed something */}
                                    {!!(browserUrlSearchOptions?.length && browserSearchTerm?.length) && (
                                        <div className="absolute top-full left-0 right-0 z-10 mt-1 bg-bg-light border border-border rounded shadow-lg max-h-48 overflow-y-auto">
                                            {browserUrlSearchOptions.slice(0, 5).map((url) => (
                                                <button
                                                    key={url}
                                                    className="w-full text-left px-3 py-2 hover:bg-bg-3000 text-sm truncate"
                                                    onClick={() => {
                                                        setDisplayUrl(url)
                                                        setBrowserSearch('')

                                                        // Copy the same URL to heatmap data URL
                                                        setDataUrl(url)
                                                    }}
                                                >
                                                    {url}
                                                </button>
                                            ))}
                                        </div>
                                    )}
                                </div>
                                <div className="mt-2">
                                    <LemonLabel>Heatmap data URL</LemonLabel>
                                    <div className="text-xs text-muted mb-1">
                                        Same as display URL by default - add * for wildcards to aggregate data from
                                        multiple pages
                                    </div>
                                    <div className="flex gap-2 justify-between">
                                        <LemonInput
                                            size="small"
                                            placeholder="Auto-generated from display URL above"
                                            value={dataUrl || ''}
                                            onChange={(value) => {
                                                setDataUrl(value || null)
                                            }}
                                            className={`truncate flex-1 ${!isBrowserUrlValid ? 'border-red-500' : ''}`}
                                            disabledReason={!displayUrl ? 'Set a valid Display URL first' : undefined}
                                        />
                                        <ExportButton iframeRef={iframeRef} />
                                    </div>
                                </div>
                            </>
                        )}
                    </div>
                </div>
                {hasValidReplayIframeData ? (
                    <LemonButton
                        size="small"
                        icon={<IconRevert />}
                        data-attr="heatmaps-reset"
                        onClick={() => {
                            setReplayIframeData(null)
                            setDataUrl(null)
                        }}
                        className="mt-2 md:mt-0"
                    >
                        Reset
                    </LemonButton>
                ) : null}
            </div>
        </>
    )
}

function HeatmapsBrowserIntro(): JSX.Element {
    const logic = heatmapsBrowserLogic()

    const { topUrls, topUrlsLoading, noPageviews } = useValues(logic)

    const { setDisplayUrl } = useActions(logic)

    return (
        <div className="flex-1 flex flex-col items-center justify-center overflow-y-auto">
            <div className="max-w-[50rem] py-6 px-3 h-full w-full">
                <div className="flex items-center flex-wrap gap-6">
                    <div className="w-50">
                        <HedgehogMagnifyingGlass className="w-full h-full" />
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

function ForbiddenURL(): JSX.Element {
    const logic = heatmapsBrowserLogic()

    const { dataUrl } = useValues(logic)

    return (
        <div className="flex-1 p-4 gap-y-4 mb-2">
            <LemonBanner type="error">
                {dataUrl} is not an authorized URL. Please add it to the list of authorized URLs to view heatmaps on
                this page.
            </LemonBanner>

            <h2>Authorized Toolbar URLs</h2>
            <AuthorizedUrlList type={AuthorizedUrlListType.TOOLBAR_URLS} />
        </div>
    )
}

function InvalidURL(): JSX.Element {
    return (
        <div className="flex-1 p-4 gap-y-4 mb-2">
            <LemonBanner type="error">Not a valid URL. Can't load a heatmap for that 😰</LemonBanner>
        </div>
    )
}

function Warnings(): JSX.Element | null {
    const { currentTeam } = useValues(teamLogic)
    const heatmapsEnabled = currentTeam?.heatmaps_opt_in

    return !heatmapsEnabled ? (
        <LemonBanner
            type="warning"
            action={{
                type: 'secondary',
                icon: <IconGear />,
                to: urls.settings('environment-heatmaps', 'heatmaps'),
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
    const clickmapLogic = recordingClickmapLogic({ iframeRef })

    const { displayUrl, isBrowserUrlAuthorized, hasValidReplayIframeData, isBrowserUrlValid } = useValues(logic)
    const { clickmapEnabled } = useValues(clickmapLogic)
    const { setClickmapEnabled } = useActions(clickmapLogic)

    return (
        <BindLogic logic={heatmapsBrowserLogic} props={logicProps}>
            <SceneContent>
                <Warnings />
                <div className="w-full">
                    <UrlSearchHeader iframeRef={iframeRef} />
                    <LemonDivider className="my-4" />
                    <FilterPanel
                        clickmapEnabled={hasValidReplayIframeData ? clickmapEnabled : undefined}
                        onClickmapEnabledChange={hasValidReplayIframeData ? setClickmapEnabled : undefined}
                    />
                    <LemonDivider className="my-4" />
                    <div className="relative border">
                        {hasValidReplayIframeData ? (
                            <FixedReplayHeatmapBrowser iframeRef={iframeRef} />
                        ) : displayUrl ? (
                            <>
                                {!isBrowserUrlAuthorized ? (
                                    <ForbiddenURL />
                                ) : !isBrowserUrlValid ? (
                                    <InvalidURL />
                                ) : (
                                    <IframeHeatmapBrowser iframeRef={iframeRef} />
                                )}
                            </>
                        ) : (
                            <HeatmapsBrowserIntro />
                        )}
                    </div>
                </div>
            </SceneContent>
        </BindLogic>
    )
}
