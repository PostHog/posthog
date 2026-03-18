import { useValues } from 'kea'
import React, { useState } from 'react'

import { IconInfo } from '@posthog/icons'

import { HEATMAP_COLOR_PALETTE_OPTIONS } from 'lib/components/heatmaps/heatmapDataLogic'
import { HeatmapFilters, HeatmapFixedPositionMode } from 'lib/components/heatmaps/types'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
import { LemonSegmentedButton } from 'lib/lemon-ui/LemonSegmentedButton'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { LemonSlider } from 'lib/lemon-ui/LemonSlider'

import { heatmapToolbarMenuLogic } from '~/toolbar/elements/heatmapToolbarMenuLogic'

const ScrollDepthJSWarning = (): JSX.Element | null => {
    const { scrollDepthPosthogJsError } = useValues(heatmapToolbarMenuLogic)

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
export const SectionSetting = ({
    children,
    title,
    info,
}: {
    children: React.ReactNode
    title: string
    info?: React.ReactNode
}): JSX.Element => {
    const [showInfo, setShowInfo] = useState(false)
    return (
        <div className="deprecated-space-y-2 mb-2">
            <div className="flex items-center gap-2">
                <LemonLabel className="flex-1">
                    <span>{title}</span>

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

interface HeatmapsSettingsProps {
    heatmapFilters?: HeatmapFilters
    patchHeatmapFilters?: (filter: Partial<HeatmapFilters>) => void
    viewportRange?: { min: number; max: number }
    heatmapColorPalette?: string | null
    setHeatmapColorPalette?: (palette: string | null) => void
    heatmapFixedPositionMode?: HeatmapFixedPositionMode
    setHeatmapFixedPositionMode?: (mode: HeatmapFixedPositionMode) => void
}

export const HeatmapsSettings = ({
    heatmapFilters,
    patchHeatmapFilters,
    viewportRange,
    heatmapColorPalette,
    setHeatmapColorPalette,
    heatmapFixedPositionMode,
    setHeatmapFixedPositionMode,
}: HeatmapsSettingsProps): JSX.Element => {
    return (
        <>
            <SectionSetting
                title="Heatmap type"
                info={
                    <>
                        Select the kind of heatmap you want to view. Clicks, rageclicks, and mouse moves options will
                        show different "heat" based on the number of interactions at that area of the page. Scroll depth
                        will show how far down the page users have reached.
                        <br />
                        Scroll depth uses additional information from Pageview and Pageleave events to indicate how far
                        down the page users have scrolled.
                    </>
                }
            >
                <div className="flex gap-2 justify-between items-center">
                    <LemonSelect
                        onChange={(e) => patchHeatmapFilters?.({ type: e })}
                        value={heatmapFilters?.type ?? undefined}
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
                                value: 'deadclick',
                                label: 'Dead clicks',
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

                    {heatmapFilters?.type === 'scrolldepth' && <ScrollDepthJSWarning />}
                </div>
            </SectionSetting>

            <SectionSetting
                title="Aggregation"
                info={
                    <>
                        Heatmaps can be aggregated by total count or unique visitors. Total count will show the total
                        number of interactions on the page, while unique visitors will only count each visitor once.
                    </>
                }
            >
                <div className="flex gap-2 justify-between items-center">
                    <LemonSegmentedButton
                        onChange={(e) => patchHeatmapFilters?.({ aggregation: e })}
                        value={heatmapFilters?.aggregation ?? 'total_count'}
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
                        The viewport accuracy setting will determine how closely the loaded data will be to your current
                        viewport.
                        <br />
                        For example if you set this to 100%, only visitors whose viewport width is identical to yours
                        will be included in the heatmap.
                        <br />
                        At 90% you will see data from viewports that are 10% smaller or larger than yours.
                    </>
                }
            >
                <div className="flex gap-2 justify-between items-center">
                    <LemonSlider
                        className="flex-1"
                        min={0}
                        max={1}
                        step={0.01}
                        value={heatmapFilters?.viewportAccuracy ?? 0}
                        onChange={(value) => patchHeatmapFilters?.({ viewportAccuracy: value })}
                    />
                    <code className="w-[12rem] text-right text-xs whitsepace-nowrap">
                        {`${Math.round((heatmapFilters?.viewportAccuracy ?? 1) * 100)}% (${viewportRange?.min}px - ${
                            viewportRange?.max
                        }px)`}
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

            {heatmapFilters?.type !== 'scrolldepth' && (
                <SectionSetting
                    title="Fixed positioning calculation"
                    info={
                        <>
                            PostHog JS will attempt to detect fixed elements such as headers or modals and will
                            therefore show those heatmap areas, ignoring the scroll value.
                            <br />
                            You can choose to show these areas as fixed, include them with scrolled data or hide them
                            altogether.
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
    )
}
