import { IconGear, IconLaptop, IconPhone, IconRevert, IconTabletLandscape, IconTabletPortrait } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonInput,
    LemonInputSelect,
    LemonSegmentedButton,
    LemonSkeleton,
} from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { AuthorizedUrlList } from 'lib/components/AuthorizedUrlList/AuthorizedUrlList'
import { appEditorUrl, AuthorizedUrlListType } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { DetectiveHog, FilmCameraHog } from 'lib/components/hedgehogs'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { useRef } from 'react'
import { FixedReplayHeatmapBrowser } from 'scenes/heatmaps/FixedReplayHeatmapBrowser'
import { teamLogic } from 'scenes/teamLogic'

import { sidePanelSettingsLogic } from '~/layout/navigation-3000/sidepanel/panels/sidePanelSettingsLogic'

import { heatmapsBrowserLogic } from './heatmapsBrowserLogic'
import { IframeHeatmapBrowser } from './IframeHeatmapBrowser'

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

export function ViewportChooser(): JSX.Element {
    const logic = heatmapsBrowserLogic()

    const { widthOverride } = useValues(logic)
    const { setIframeWidth } = useActions(logic)

    return (
        <div className="flex justify-center mb-2">
            <LemonSegmentedButton
                onChange={setIframeWidth}
                value={widthOverride ? widthOverride : undefined}
                data-attr="viewport-chooser"
                options={[
                    {
                        value: 320,
                        label: (
                            <div className="px-1">
                                <IconPhone />
                                <div className="text-xs">320px</div>
                            </div>
                        ),
                    },
                    {
                        value: 375,
                        label: (
                            <div className="px-1">
                                <IconPhone />
                                <div className="text-xs">375px</div>
                            </div>
                        ),
                    },
                    {
                        value: 425,
                        label: (
                            <div className="px-1">
                                <IconPhone />
                                <div className="text-xs">425px</div>
                            </div>
                        ),
                    },
                    {
                        value: 768,
                        label: (
                            <div className="px-1">
                                <IconTabletPortrait />
                                <div className="text-xs">768px</div>
                            </div>
                        ),
                    },
                    {
                        value: 1024,
                        label: (
                            <div className="px-1">
                                <IconTabletLandscape />
                                <div className="text-xs">1024px</div>
                            </div>
                        ),
                    },
                    {
                        value: 1440,
                        label: (
                            <div className="px-1">
                                <IconLaptop />
                                <div className="text-xs">1440px</div>
                            </div>
                        ),
                    },
                    {
                        value: 1920,
                        label: (
                            <div className="px-1">
                                <IconLaptop />
                                <div className="text-xs">1920px</div>
                            </div>
                        ),
                    },
                ]}
                size="small"
            />
        </div>
    )
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
                                    <IframeHeatmapBrowser iframeRef={iframeRef} />
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
