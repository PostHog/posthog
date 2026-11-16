import { useActions, useValues } from 'kea'

import { IconMagicWand, IconTarget } from '@posthog/icons'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { HeatmapsSettings } from 'lib/components/heatmaps/HeatMapsSettings'
import { heatmapDateOptions } from 'lib/components/IframedToolbarBrowser/utils'
import { IconSync } from 'lib/lemon-ui/icons'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonSnack } from 'lib/lemon-ui/LemonSnack'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { Link } from 'lib/lemon-ui/Link'
import { Spinner } from 'lib/lemon-ui/Spinner'

import { urls } from '~/toolbar/shared/urls'

import { capturePageToolUsed } from '../../browser/extensionTelemetry'
import type { PageHeatmapCommand } from '../../logics/page/extensionPageHeatmapLogic'
import { extensionPageToolbarConnectionLogic } from '../../logics/panel/extensionPageToolbarConnectionLogic'
import { extensionPanelLogic } from '../../logics/panel/extensionPanelLogic'
import type { PageToolbarHeatmapState } from '../../messaging/pageToolbarBridge'
import { ExtensionInspectedElement } from '../elements/ExtensionInspectedElement'

function HeatmapsCollectionWarning({ heatmap }: { heatmap: PageToolbarHeatmapState }): JSX.Element | null {
    const { projectUrl } = useValues(extensionPanelLogic)
    if (heatmap.heatmapsCollection === 'unsupported') {
        return (
            <LemonBanner type="warning">
                The version of posthog-js on this page doesn't collect heatmap data.
            </LemonBanner>
        )
    }
    if (heatmap.heatmapsCollection === 'disabled') {
        return (
            <LemonBanner type="warning">
                This page doesn't collect heatmap data. Turn it on in your posthog-js configuration or{' '}
                <Link to={projectUrl(urls.settings('environment-heatmaps', 'heatmaps'))} target="_blank">
                    in your project settings
                </Link>
                .
            </LemonBanner>
        )
    }
    return null
}

function HeatmapSaveResultMessage({ heatmap }: { heatmap: PageToolbarHeatmapState }): JSX.Element | null {
    const { openHeatmapInPostHog } = useActions(extensionPageToolbarConnectionLogic)
    const result = heatmap.saveResult
    if (!result || heatmap.savingHeatmap) {
        return null
    }
    if (result.status === 'failed') {
        return <div className="text-danger text-xs">Couldn't save this heatmap: {result.error}</div>
    }
    const allWidths = result.savedWidths === result.totalWidths
    return (
        <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className={allWidths ? 'text-success' : 'text-warning'}>
                {allWidths
                    ? 'Heatmap saved.'
                    : result.savedWidths === 0
                      ? 'Heatmap saved at your current window width only.'
                      : `Heatmap saved with ${result.savedWidths} of ${result.totalWidths} page widths.`}
            </span>
            <LemonButton
                size="xsmall"
                type="secondary"
                onClick={() => openHeatmapInPostHog(result.shortId)}
                data-attr="toolbar-extension-open-saved-heatmap"
            >
                Open in PostHog
            </LemonButton>
        </div>
    )
}

export function ExtensionHeatmapMenu(): JSX.Element {
    const { heatmap, wildcardHrefDraft } = useValues(extensionPageToolbarConnectionLogic)
    const { sendCommand, setWildcardHref } = useActions(extensionPageToolbarConnectionLogic)
    const sendHeatmapCommand = (command: PageHeatmapCommand): void => sendCommand({ tool: 'heatmap', command })

    if (!heatmap) {
        return (
            <div className="flex items-center gap-2 text-secondary">
                <Spinner />
                Loading the heatmap…
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-3">
            <div className="flex flex-col gap-1">
                <div className="flex gap-1">
                    <LemonInput
                        className="flex-1 min-w-0"
                        size="small"
                        value={wildcardHrefDraft ?? heatmap.wildcardHref}
                        onChange={setWildcardHref}
                    />
                    <LemonButton
                        size="small"
                        type={heatmap.autoWildcardEnabled ? 'primary' : 'secondary'}
                        icon={<IconMagicWand />}
                        onClick={() => sendHeatmapCommand({ type: 'auto-wildcard-href' })}
                        tooltip={
                            <>
                                Use <code>*</code> to match any characters in the URL. Click to add wildcards where they
                                make sense.
                            </>
                        }
                        data-attr="toolbar-extension-heatmap-wildcard"
                    />
                </div>
                <LemonSwitch
                    size="small"
                    checked={heatmap.autoWildcardEnabled}
                    onChange={(enabled) => sendHeatmapCommand({ type: 'set-auto-wildcard-enabled', enabled })}
                    label="Add wildcards when you go to another page"
                />
                {heatmap.wildcardHrefTooSpecific && (
                    <div className="text-xs text-secondary">
                        {heatmap.wildcardHrefEndsWithSlash ? (
                            <>
                                A trailing slash matches only URLs that end there, so deeper pages and query strings
                                drop out. Use <code>*</code> to include them.
                            </>
                        ) : (
                            <>
                                This URL is specific, so it matches less data. Use <code>*</code> as a wildcard to match
                                more.
                            </>
                        )}
                    </div>
                )}
            </div>

            <div className="flex flex-wrap items-center gap-2">
                <DateFilter
                    dateFrom={heatmap.commonFilters.date_from}
                    dateTo={heatmap.commonFilters.date_to}
                    onChange={(dateFrom, dateTo) =>
                        sendHeatmapCommand({
                            type: 'set-common-filters',
                            filters: { date_from: dateFrom, date_to: dateTo },
                        })
                    }
                    dateOptions={heatmapDateOptions}
                />
                <LemonButton
                    size="small"
                    type="secondary"
                    icon={<IconTarget />}
                    active={heatmap.areaSelectionActive}
                    onClick={() =>
                        sendHeatmapCommand({
                            type: heatmap.areaSelectionActive ? 'cancel-area-selection' : 'start-area-selection',
                        })
                    }
                    tooltip="Limit the heatmap and clickmap to one part of the page. Click this, then click an area on the page. Press ↑ or ↓ to grow or shrink the area, and Esc to cancel."
                    data-attr="toolbar-extension-heatmap-area-filter"
                >
                    {heatmap.areaSelectionActive ? 'Click an area of the page…' : 'Filter to area'}
                </LemonButton>
            </div>
            {heatmap.areaFilter && !heatmap.areaSelectionActive && (
                <div className="flex items-center gap-2">
                    <span className="text-secondary text-xs">Filtered to</span>
                    <LemonSnack
                        className="font-mono text-xs shrink min-w-0 truncate"
                        onClose={() => sendHeatmapCommand({ type: 'clear-area-filter' })}
                    >
                        {heatmap.areaFilter.selector ?? `<${heatmap.areaFilter.tagName}>`}
                    </LemonSnack>
                </div>
            )}

            <div className="flex flex-col gap-2 border-t pt-2">
                <LemonSwitch
                    fullWidth
                    bordered
                    label={
                        <span className="flex items-center gap-2">
                            Heatmaps {heatmap.rawHeatmapLoading && <Spinner />}
                        </span>
                    }
                    checked={!!heatmap.heatmapFilters.enabled}
                    onChange={(enabled) => sendHeatmapCommand({ type: 'patch-heatmap-filters', filters: { enabled } })}
                    data-attr="toolbar-extension-heatmap-canvas-toggle"
                />
                {heatmap.heatmapFilters.enabled && (
                    <>
                        <HeatmapsCollectionWarning heatmap={heatmap} />
                        <div className="text-xs text-secondary">
                            Heatmaps use pointer data sent with standard events. They might not match the page you see
                            exactly.
                        </div>
                        <HeatmapsSettings
                            heatmapFilters={heatmap.heatmapFilters}
                            patchHeatmapFilters={(filters) =>
                                sendHeatmapCommand({ type: 'patch-heatmap-filters', filters })
                            }
                            viewportRange={heatmap.viewportRange}
                            heatmapColorPalette={heatmap.heatmapColorPalette}
                            setHeatmapColorPalette={(palette) =>
                                sendHeatmapCommand({ type: 'set-color-palette', palette })
                            }
                            heatmapFixedPositionMode={heatmap.heatmapFixedPositionMode}
                            setHeatmapFixedPositionMode={(mode) =>
                                sendHeatmapCommand({ type: 'set-fixed-position-mode', mode })
                            }
                            scrollDepthPosthogJsError={heatmap.scrollDepthPosthogJsError}
                        />
                        <LemonButton
                            type="primary"
                            fullWidth
                            center
                            loading={heatmap.savingHeatmap}
                            onClick={() => {
                                capturePageToolUsed('save-heatmap')
                                sendHeatmapCommand({ type: 'save-heatmap' })
                            }}
                            data-attr="toolbar-extension-heatmap-save"
                        >
                            {heatmap.savingHeatmap && heatmap.saveProgress
                                ? `Capturing screen widths (${heatmap.saveProgress.done}/${heatmap.saveProgress.total})`
                                : 'Save to PostHog'}
                        </LemonButton>
                        <div className="text-xs text-secondary">
                            Captures this page at several screen widths and saves them with the heatmap, so you can open
                            it in PostHog later. Works when the page is behind a login.
                        </div>
                        <HeatmapSaveResultMessage heatmap={heatmap} />
                    </>
                )}
            </div>

            <div className="flex flex-col gap-2 border-t pt-2">
                <LemonSwitch
                    fullWidth
                    bordered
                    label={
                        <span className="flex items-center gap-2">
                            Clickmaps (autocapture){' '}
                            {(heatmap.clickmapLoading || !!heatmap.processingProgress) && <Spinner />}
                        </span>
                    }
                    checked={heatmap.clickmapsEnabled}
                    onChange={(enabled) => sendHeatmapCommand({ type: 'set-clickmaps-enabled', enabled })}
                    data-attr="toolbar-extension-clickmap-toggle"
                />
                {heatmap.clickmapsEnabled && (
                    <>
                        <div className="text-xs text-secondary">
                            Clickmaps use autocapture events. They match clicks to the elements on this page. Hold{' '}
                            <kbd>shift</kbd> to click the page under the clickmap.
                        </div>
                        <div className="flex flex-wrap items-center gap-2">
                            <LemonButton
                                size="small"
                                type="secondary"
                                icon={heatmap.loadingAllElementStats ? <Spinner textColored /> : <IconSync />}
                                active={heatmap.loadingAllElementStats}
                                disabledReason={
                                    heatmap.canLoadMoreElementStats || heatmap.loadingAllElementStats
                                        ? null
                                        : 'All elements in this date range are loaded'
                                }
                                onClick={() =>
                                    sendHeatmapCommand({
                                        type: heatmap.loadingAllElementStats
                                            ? 'stop-loading-all-element-stats'
                                            : 'load-all-element-stats',
                                    })
                                }
                                data-attr="toolbar-extension-clickmap-load-all"
                            >
                                {heatmap.loadingAllElementStats ? 'Stop loading' : 'Load all'}
                            </LemonButton>
                            <LemonSwitch
                                className="flex-1"
                                size="small"
                                bordered
                                checked={heatmap.matchLinksByHref}
                                onChange={(matchLinksByHref) =>
                                    sendHeatmapCommand({ type: 'set-match-links-by-href', matchLinksByHref })
                                }
                                label="Match links by their target URL"
                            />
                        </div>
                        <div className="text-xs">
                            <span translate="no">
                                {heatmap.countedElements.length} elements / {heatmap.clickCount} clicks
                            </span>
                            {heatmap.processingProgress && (
                                <span className="text-secondary" translate="no">
                                    {' '}
                                    (processing {heatmap.processingProgress.processed.toLocaleString()}/
                                    {heatmap.processingProgress.total.toLocaleString()})
                                </span>
                            )}
                        </div>
                        {heatmap.canLoadMoreElementStats && heatmap.loadedElementStatsCount > 0 && (
                            <div className="text-xs text-secondary">
                                Showing the top {heatmap.loadedElementStatsCount.toLocaleString()} element groups by
                                click count. Load all to include the whole date range.
                            </div>
                        )}
                        <ExtensionInspectedElement />
                        <div className="flex flex-col">
                            {heatmap.countedElements.length === 0 ? (
                                <div className="text-secondary text-xs">
                                    {heatmap.clickmapLoading ? 'Loading clicks…' : 'No clicked elements found.'}
                                </div>
                            ) : (
                                heatmap.countedElements.map((element, index) => (
                                    <LemonButton
                                        key={index}
                                        size="small"
                                        fullWidth
                                        onClick={() => sendHeatmapCommand({ type: 'select-counted-element', index })}
                                        onMouseEnter={() =>
                                            sendHeatmapCommand({ type: 'highlight-counted-element', index })
                                        }
                                        onMouseLeave={() =>
                                            sendHeatmapCommand({ type: 'highlight-counted-element', index: null })
                                        }
                                    >
                                        <span className="flex flex-1 min-w-0 justify-between gap-2">
                                            <span className="truncate">
                                                {index + 1}. {element.text || <code>&lt;{element.tagName}&gt;</code>}
                                            </span>
                                            <span className="shrink-0" translate="no">
                                                {element.count} clicks
                                            </span>
                                        </span>
                                    </LemonButton>
                                ))
                            )}
                        </div>
                    </>
                )}
            </div>
        </div>
    )
}
