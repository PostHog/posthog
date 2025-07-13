import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import React from 'react'

import { IconMagicWand } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'
import { LemonButton, LemonSwitch } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { heatmapDateOptions } from 'lib/components/IframedToolbarBrowser/utils'
import { HeatmapsSettings } from 'lib/components/heatmaps/HeatMapsSettings'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
import { LemonSegmentedButton } from 'lib/lemon-ui/LemonSegmentedButton'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { IconSync } from 'lib/lemon-ui/icons'

import { ToolbarMenu } from '~/toolbar/bar/ToolbarMenu'
import { elementsLogic } from '~/toolbar/elements/elementsLogic'
import { heatmapToolbarMenuLogic } from '~/toolbar/elements/heatmapToolbarMenuLogic'
import { currentPageLogic } from '~/toolbar/stats/currentPageLogic'

import { toolbarConfigLogic } from '../toolbarConfigLogic'

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
                    You can enable heatmap collection in your posthog-js configuration or{' '}
                    <Link to="https://us.posthog.com/settings/project#heatmaps">in your project config</Link>.
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
        samplingFactor,
    } = useValues(heatmapToolbarMenuLogic)
    const {
        setCommonFilters,
        patchHeatmapFilters,
        loadMoreElementStats,
        setMatchLinksByHref,
        toggleClickmapsEnabled,
        setHeatmapFixedPositionMode,
        setHeatmapColorPalette,
        setSamplingFactor,
    } = useActions(heatmapToolbarMenuLogic)
    const { setHighlightElement, setSelectedElement } = useActions(elementsLogic)

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
                    <DateFilter
                        dateFrom={commonFilters.date_from}
                        dateTo={commonFilters.date_to}
                        onChange={(fromDate, toDate) => {
                            setCommonFilters({ date_from: fromDate, date_to: toDate })
                        }}
                        dateOptions={heatmapDateOptions}
                    />
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
                        Heatmaps
                    </SectionButton>

                    {heatmapFilters.enabled && (
                        <>
                            <HeatmapsJSWarning />
                            <p>
                                Heatmaps are calculated using additional data sent along with standard events. They are
                                based off of general pointer interactions and might not be 100% accurate to the page you
                                are viewing.
                            </p>

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
                            <div className="flex items-center justify-between pb-2">
                                <div className="flex items-center gap-1">
                                    <LemonLabel
                                        info="Sampling computes the result on a proportion of data of the users in the dataset, making click maps load significantly faster."
                                        infoLink="https://posthog.com/docs/product-analytics/sampling"
                                    >
                                        Sampling
                                    </LemonLabel>
                                    <LemonSwitch
                                        className="m-2"
                                        onChange={(checked) => {
                                            if (checked) {
                                                setSamplingFactor(0.1)
                                                posthog.capture('sampling_enabled_on_heatmap')
                                                return
                                            }
                                            setSamplingFactor(1)
                                            posthog.capture('sampling_disabled_on_heatmap')
                                        }}
                                        checked={samplingFactor !== 1}
                                    />
                                </div>
                                {samplingFactor !== 1 && (
                                    <div className="flex items-center gap-2">
                                        <LemonSegmentedButton
                                            options={[0.1, 1, 10, 25, 50].map((percentage) => ({
                                                value: percentage / 100,
                                                label: `${percentage}%`,
                                            }))}
                                            value={samplingFactor}
                                            onChange={(newValue) => {
                                                setSamplingFactor(newValue)
                                                posthog.capture('sampling_percentage_updated_on_heatmap', {
                                                    samplingFactor: newValue,
                                                })
                                            }}
                                        />
                                    </div>
                                )}
                            </div>
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
