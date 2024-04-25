import { IconMagicWand } from '@posthog/icons'
import { LemonLabel, LemonSegmentedButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { CUSTOM_OPTION_KEY } from 'lib/components/DateFilter/types'
import { IconSync } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
import { LemonSlider } from 'lib/lemon-ui/LemonSlider'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { dateFilterToText, dateMapping } from 'lib/utils'

import { ToolbarMenu } from '~/toolbar/bar/ToolbarMenu'
import { elementsLogic } from '~/toolbar/elements/elementsLogic'
import { heatmapLogic } from '~/toolbar/elements/heatmapLogic'
import { currentPageLogic } from '~/toolbar/stats/currentPageLogic'

import { useToolbarFeatureFlag } from '../toolbarPosthogJS'

const ScrollDepthJSWarning = (): JSX.Element | null => {
    const { scrollDepthPosthogJsError } = useValues(heatmapLogic)

    if (!scrollDepthPosthogJsError) {
        return null
    }

    return (
        <p className="my-2 bg-danger-highlight border border-danger rounded p-2">
            {scrollDepthPosthogJsError === 'version' ? (
                <>This feature requires a newer version of posthog-js</>
            ) : scrollDepthPosthogJsError === 'disabled' ? (
                <>
                    Your posthog-js config has <i>disable_scroll_properties</i> set - these properties are required for
                    scroll depth calculations to work.
                </>
            ) : null}
        </p>
    )
}

export const HeatmapToolbarMenu = (): JSX.Element => {
    const { wildcardHref } = useValues(currentPageLogic)
    const { setWildcardHref, autoWildcardHref } = useActions(currentPageLogic)

    const {
        matchLinksByHref,
        countedElements,
        clickCount,
        commonFilters,
        heatmapFilters,
        canLoadMoreElementStats,
        viewportRange,
        rawHeatmapLoading,
        elementStatsLoading,
        clickmapsEnabled,
        heatmapFixedPositionMode,
    } = useValues(heatmapLogic)
    const {
        setCommonFilters,
        patchHeatmapFilters,
        loadMoreElementStats,
        setMatchLinksByHref,
        toggleClickmapsEnabled,
        setHeatmapFixedPositionMode,
    } = useActions(heatmapLogic)
    const { setHighlightElement, setSelectedElement } = useActions(elementsLogic)

    const dateItems = dateMapping
        .filter((dm) => dm.key !== CUSTOM_OPTION_KEY)
        .map((dateOption) => ({
            label: dateOption.key,
            onClick: () => setCommonFilters({ date_from: dateOption.values[0], date_to: dateOption.values[1] }),
        }))

    const showNewHeatmaps = useToolbarFeatureFlag('toolbar-heatmaps')

    return (
        <ToolbarMenu>
            <ToolbarMenu.Header>
                <div className="flex gap-1">
                    <LemonInput className="flex-1" value={wildcardHref} onChange={setWildcardHref} />
                    <LemonButton
                        type="secondary"
                        icon={<IconMagicWand />}
                        size="small"
                        onClick={() => autoWildcardHref()}
                        tooltip={
                            <>
                                You can use the wildcard character <code>*</code> to match any character in the URL. For
                                example, <code>https://example.com/*</code> will match{' '}
                                <code>https://example.com/page</code> and <code>https://example.com/page/1</code>.
                                <br />
                                Click this button to automatically wildcards where we believe it would make sense
                            </>
                        }
                    />
                </div>

                <div className="flex flex-row items-center gap-2 py-2 border-b">
                    <LemonMenu items={dateItems}>
                        <LemonButton size="small" type="secondary">
                            {dateFilterToText(commonFilters.date_from, commonFilters.date_to, 'Last 7 days')}
                        </LemonButton>
                    </LemonMenu>
                </div>
            </ToolbarMenu.Header>
            <ToolbarMenu.Body>
                {showNewHeatmaps ? (
                    <div className="border-b p-2">
                        <LemonSwitch
                            className="w-full"
                            checked={!!heatmapFilters.enabled}
                            label={<>Heatmaps {rawHeatmapLoading ? <Spinner /> : null}</>}
                            onChange={(e) =>
                                patchHeatmapFilters({
                                    enabled: e,
                                })
                            }
                        />

                        {heatmapFilters.enabled && (
                            <>
                                <p>
                                    Heatmaps are calculated using additional data sent along with standard events. They
                                    are based off of general pointer interactions and might not be 100% accurate to the
                                    page you are viewing.
                                </p>
                                <div className="space-y-2">
                                    <LemonLabel>Heatmap type</LemonLabel>
                                    <div className="flex gap-2 justify-between items-center">
                                        <LemonSegmentedButton
                                            onChange={(e) => patchHeatmapFilters({ type: e })}
                                            value={heatmapFilters.type ?? undefined}
                                            options={[
                                                {
                                                    value: 'click',
                                                    label: 'Clicks',
                                                },
                                                {
                                                    value: 'rageclick',
                                                    label: 'Rageclicks',
                                                },
                                                {
                                                    value: 'mousemove',
                                                    label: 'Mouse moves',
                                                },
                                                {
                                                    value: 'scrolldepth',
                                                    label: 'Scroll depth',
                                                },
                                            ]}
                                            size="small"
                                        />
                                    </div>

                                    {heatmapFilters.type === 'scrolldepth' && (
                                        <>
                                            <p>
                                                Scroll depth uses additional information from Pageview and Pageleave
                                                events to indicate how far down the page users have scrolled.
                                            </p>
                                            <ScrollDepthJSWarning />
                                        </>
                                    )}

                                    <LemonLabel>Show</LemonLabel>
                                    <div className="flex gap-2 justify-between items-center">
                                        <LemonSegmentedButton
                                            onChange={(e) => patchHeatmapFilters({ aggregation: e })}
                                            value={heatmapFilters.aggregation ?? 'total_count'}
                                            options={[
                                                {
                                                    value: 'total_count',
                                                    label: 'Total count',
                                                },
                                                {
                                                    value: 'unique_visitors',
                                                    label: 'Unique visitors',
                                                },
                                                {
                                                    value: 'recordings',
                                                    label: 'Recordings',
                                                },
                                            ]}
                                            size="small"
                                        />
                                    </div>

                                    <LemonLabel>Viewport accuracy</LemonLabel>
                                    <div className="flex gap-2 justify-between items-center">
                                        <LemonSlider
                                            className="flex-1"
                                            min={0}
                                            max={1}
                                            step={0.01}
                                            value={heatmapFilters.viewportAccuracy ?? 0}
                                            onChange={(value) => patchHeatmapFilters({ viewportAccuracy: value })}
                                        />
                                        <Tooltip
                                            title={`
                                    The range of values 
                                    Heatmap will be loaded for all viewports where the width is above 

                                    `}
                                        >
                                            <code className="w-[12rem] text-right text-xs whitsepace-nowrap">
                                                {`${Math.round((heatmapFilters.viewportAccuracy ?? 1) * 100)}% (${
                                                    viewportRange.min
                                                }px - ${viewportRange.max}px)`}
                                            </code>
                                        </Tooltip>
                                    </div>

                                    {heatmapFilters.type !== 'scrolldepth' ? (
                                        <>
                                            <LemonLabel>Fixed positioning calculation</LemonLabel>
                                            <p>
                                                PostHog JS will attempt to detect fixed elements such as headers or
                                                modals and will therefore show those heatmap areas, ignoring the scroll
                                                value.
                                                <br />
                                                You can choose to show these areas as fixed, include them with scrolled
                                                data or hide them altogether.
                                            </p>

                                            <LemonSegmentedButton
                                                onChange={setHeatmapFixedPositionMode}
                                                value={heatmapFixedPositionMode}
                                                options={[
                                                    {
                                                        value: 'fixed',
                                                        label: 'Show fixed',
                                                    },
                                                    {
                                                        value: 'relative',
                                                        label: 'Show scrolled',
                                                    },
                                                    {
                                                        value: 'hidden',
                                                        label: 'Hide',
                                                    },
                                                ]}
                                                size="small"
                                            />
                                        </>
                                    ) : null}
                                </div>
                            </>
                        )}
                    </div>
                ) : null}

                <div className="p-2">
                    {showNewHeatmaps ? (
                        <LemonSwitch
                            className="w-full"
                            checked={!!clickmapsEnabled}
                            label={<>Clickmaps (autocapture) {elementStatsLoading ? <Spinner /> : null}</>}
                            onChange={(e) => toggleClickmapsEnabled(e)}
                        />
                    ) : null}

                    {(clickmapsEnabled || !showNewHeatmaps) && (
                        <>
                            {showNewHeatmaps ? (
                                <p>
                                    Clickmaps are built using Autocapture events. They are more accurate than heatmaps
                                    if the event can be mapped to a specific element found on the page you are viewing
                                    but less data is usually captured.
                                </p>
                            ) : null}
                            <div className="flex items-center gap-2">
                                <LemonButton
                                    icon={<IconSync />}
                                    type="secondary"
                                    size="small"
                                    onClick={loadMoreElementStats}
                                    disabledReason={
                                        canLoadMoreElementStats ? undefined : 'Loaded all elements in this data range.'
                                    }
                                >
                                    Load more
                                </LemonButton>
                                <Tooltip
                                    title={
                                        <span>
                                            Matching links by their target URL can exclude clicks from the heatmap if
                                            the URL is too unique.
                                        </span>
                                    }
                                >
                                    <LemonSwitch
                                        className="flex-1"
                                        checked={matchLinksByHref}
                                        label="Match links by their target URL"
                                        onChange={(checked) => setMatchLinksByHref(checked)}
                                        fullWidth={true}
                                        bordered={true}
                                    />
                                </Tooltip>
                            </div>

                            <div className="my-2">
                                Found: {countedElements.length} elements / {clickCount} clicks!
                            </div>
                            <div className="flex flex-col w-full h-full">
                                {countedElements.length ? (
                                    countedElements.map(({ element, count, actionStep }, index) => {
                                        return (
                                            <LemonButton
                                                key={index}
                                                size="small"
                                                fullWidth
                                                onClick={() => setSelectedElement(element)}
                                            >
                                                <div
                                                    className="flex flex-1 justify-between"
                                                    key={index}
                                                    onMouseEnter={() => setHighlightElement(element)}
                                                    onMouseLeave={() => setHighlightElement(null)}
                                                >
                                                    <div>
                                                        {index + 1}.&nbsp;
                                                        {actionStep?.text ||
                                                            (actionStep?.tag_name ? (
                                                                <code>&lt;{actionStep.tag_name}&gt;</code>
                                                            ) : (
                                                                <em>Element</em>
                                                            ))}
                                                    </div>
                                                    <div>{count} clicks</div>
                                                </div>
                                            </LemonButton>
                                        )
                                    })
                                ) : (
                                    <div className="p-2">No elements found.</div>
                                )}
                            </div>
                        </>
                    )}
                </div>
            </ToolbarMenu.Body>
        </ToolbarMenu>
    )
}
