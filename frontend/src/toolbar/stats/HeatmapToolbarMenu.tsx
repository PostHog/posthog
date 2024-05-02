import { IconInfo, IconMagicWand } from '@posthog/icons'
import { LemonLabel, LemonSegmentedButton, LemonSelect, LemonTag } from '@posthog/lemon-ui'
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
import React, { useState } from 'react'

import { ToolbarMenu } from '~/toolbar/bar/ToolbarMenu'
import { elementsLogic } from '~/toolbar/elements/elementsLogic'
import { HEATMAP_COLOR_PALETTE_OPTIONS, heatmapLogic } from '~/toolbar/elements/heatmapLogic'
import { currentPageLogic } from '~/toolbar/stats/currentPageLogic'

import { toolbarConfigLogic } from '../toolbarConfigLogic'

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

const HeatmapsJSWarning = (): JSX.Element | null => {
    const { posthog } = useValues(toolbarConfigLogic)

    if (!posthog || posthog?.heatmaps?.isEnabled) {
        return null
    }

    return (
        <p className="my-2 bg-danger-highlight border border-danger rounded p-2">
            {!posthog.heatmaps ? (
                <>The version of posthog-js you are using does not support collecting heatmap data.</>
            ) : !posthog.heatmaps.isEnabled ? (
                <>
                    Heatmap collection is disabled in your posthog-js configuration. If you do not see heatmap data then
                    this is likely why.
                </>
            ) : null}
        </p>
    )
}

const SectionButton = ({
    children,
    checked,
    onChange,
    loading,
}: {
    children: React.ReactNode
    checked: boolean
    onChange: (checked: boolean) => void
    loading?: boolean
}): JSX.Element => {
    return (
        <div className="flex items-center">
            <LemonButton
                className="flex-1 -mx-2 p-2"
                noPadding
                onClick={() => onChange(!checked)}
                sideIcon={<LemonSwitch checked={checked} />}
            >
                <span className="flex items-center gap-2">
                    {children}

                    {loading ? <Spinner /> : null}
                </span>
            </LemonButton>
        </div>
    )
}

const SectionSetting = ({
    children,
    title,
    info,
}: {
    children: React.ReactNode
    title: React.ReactNode
    info?: React.ReactNode
}): JSX.Element => {
    const [showInfo, setShowInfo] = useState(false)
    return (
        <div className="space-y-2 mb-2">
            <div className="flex items-center gap-2">
                <LemonLabel className="flex-1">
                    {title}

                    {info && (
                        <LemonButton
                            icon={<IconInfo />}
                            size="xsmall"
                            active={showInfo}
                            onClick={() => setShowInfo(!showInfo)}
                            noPadding
                        />
                    )}
                </LemonLabel>
            </div>

            {showInfo ? <div className="text-sm">{info}</div> : null}

            {children}
        </div>
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
        heatmapColorPalette,
    } = useValues(heatmapLogic)
    const {
        setCommonFilters,
        patchHeatmapFilters,
        loadMoreElementStats,
        setMatchLinksByHref,
        toggleClickmapsEnabled,
        setHeatmapFixedPositionMode,
        setHeatmapColorPalette,
    } = useActions(heatmapLogic)
    const { setHighlightElement, setSelectedElement } = useActions(elementsLogic)

    // some of the date options we allow in insights don't apply to heatmaps
    // let's filter the list down
    const dateItemDenyList = ['Last 180 days', 'This month', 'Previous month', 'Year to date', 'All time']

    const dateItems = dateMapping
        .filter((dm) => dm.key !== CUSTOM_OPTION_KEY && !dateItemDenyList.includes(dm.key))
        .map((dateOption) => ({
            label: dateOption.key,
            onClick: () => setCommonFilters({ date_from: dateOption.values[0], date_to: dateOption.values[1] }),
        }))

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
                <div className="border-b p-2">
                    <SectionButton
                        onChange={(e) =>
                            patchHeatmapFilters({
                                enabled: e,
                            })
                        }
                        loading={rawHeatmapLoading}
                        checked={!!heatmapFilters.enabled}
                    >
                        Heatmaps <LemonTag type="highlight">NEW</LemonTag>{' '}
                    </SectionButton>

                    {heatmapFilters.enabled && (
                        <>
                            <HeatmapsJSWarning />
                            <p>
                                Heatmaps are calculated using additional data sent along with standard events. They are
                                based off of general pointer interactions and might not be 100% accurate to the page you
                                are viewing.
                            </p>

                            <SectionSetting
                                title="Heatmap type"
                                info={
                                    <>
                                        Select the kind of heatmap you want to view. Clicks, rageclicks, and mouse moves
                                        options will show different "heat" based on the number of interactions at that
                                        area of the page. Scroll depth will show how far down the page users have
                                        reached.
                                        <br />
                                        Scroll depth uses additional information from Pageview and Pageleave events to
                                        indicate how far down the page users have scrolled.
                                    </>
                                }
                            >
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

                                    {heatmapFilters.type === 'scrolldepth' && <ScrollDepthJSWarning />}
                                </div>
                            </SectionSetting>

                            <SectionSetting
                                title="Aggregation"
                                info={
                                    <>
                                        Heatmaps can be aggregated by total count or unique visitors. Total count will
                                        show the total number of interactions on the page, while unique visitors will
                                        only count each visitor once.
                                    </>
                                }
                            >
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
                                        ]}
                                        size="small"
                                    />
                                </div>
                            </SectionSetting>

                            <SectionSetting
                                title="Viewport accuracy"
                                info={
                                    <>
                                        The viewport accuracy setting will determine how closely the loaded data will be
                                        to your current viewport.
                                        <br />
                                        For example if you set this to 100%, only visitors whose viewport width is
                                        identical to yours will be included in the heatmap.
                                        <br />
                                        At 90% you will see data from viewports that are 10% smaller or larger than
                                        yours.
                                    </>
                                }
                            >
                                <div className="flex gap-2 justify-between items-center">
                                    <LemonSlider
                                        className="flex-1"
                                        min={0}
                                        max={1}
                                        step={0.01}
                                        value={heatmapFilters.viewportAccuracy ?? 0}
                                        onChange={(value) => patchHeatmapFilters({ viewportAccuracy: value })}
                                    />
                                    <code className="w-[12rem] text-right text-xs whitsepace-nowrap">
                                        {`${Math.round((heatmapFilters.viewportAccuracy ?? 1) * 100)}% (${
                                            viewportRange.min
                                        }px - ${viewportRange.max}px)`}
                                    </code>
                                </div>
                            </SectionSetting>

                            <SectionSetting title="Color palette">
                                <LemonSelect
                                    size="small"
                                    options={HEATMAP_COLOR_PALETTE_OPTIONS}
                                    value={heatmapColorPalette}
                                    onChange={setHeatmapColorPalette}
                                />
                            </SectionSetting>

                            {heatmapFilters.type !== 'scrolldepth' && (
                                <SectionSetting
                                    title="Fixed positioning calculation"
                                    info={
                                        <>
                                            PostHog JS will attempt to detect fixed elements such as headers or modals
                                            and will therefore show those heatmap areas, ignoring the scroll value.
                                            <br />
                                            You can choose to show these areas as fixed, include them with scrolled data
                                            or hide them altogether.
                                        </>
                                    }
                                >
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
                                </SectionSetting>
                            )}
                        </>
                    )}
                </div>

                <div className="p-2">
                    <SectionButton
                        onChange={(e) => toggleClickmapsEnabled(e)}
                        loading={elementStatsLoading}
                        checked={!!clickmapsEnabled}
                    >
                        Clickmaps (autocapture)
                    </SectionButton>

                    {clickmapsEnabled && (
                        <>
                            <p>
                                Clickmaps are built using Autocapture events. They are more accurate than heatmaps if
                                the event can be mapped to a specific element found on the page you are viewing but less
                                data is usually captured.
                            </p>
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
