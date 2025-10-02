import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconGear, IconLaptop, IconPhone, IconTabletLandscape, IconTabletPortrait } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSelect } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { heatmapDateOptions } from 'lib/components/IframedToolbarBrowser/utils'
import { HeatmapsSettings } from 'lib/components/heatmaps/HeatMapsSettings'
import { heatmapDataLogic } from 'lib/components/heatmaps/heatmapDataLogic'
import { LoadingBar } from 'lib/lemon-ui/LoadingBar'
import { Popover } from 'lib/lemon-ui/Popover'
import { inStorybook, inStorybookTestRunner } from 'lib/utils'
import { TestAccountFilter } from 'scenes/insights/filters/TestAccountFilter'

import { heatmapsBrowserLogic } from './heatmapsBrowserLogic'

const useDebounceLoading = (loading: boolean, delay = 200): boolean => {
    const [debouncedLoading, setDebouncedLoading] = useState(false)

    useEffect(() => {
        const timer = setTimeout(() => {
            setDebouncedLoading(loading)
        }, delay)

        return () => clearTimeout(timer)
    }, [loading, delay])

    return debouncedLoading
}

export function ViewportChooser(): JSX.Element {
    const logic = heatmapsBrowserLogic()

    const { widthOverride } = useValues(logic)
    const { setIframeWidth } = useActions(logic)

    const options = [
        {
            value: 320,
            icon: <IconPhone />,
        },
        {
            value: 375,
            icon: <IconPhone />,
        },
        {
            value: 425,
            icon: <IconPhone />,
        },
        {
            value: 768,
            icon: <IconTabletPortrait />,
        },
        {
            value: 1024,
            icon: <IconTabletLandscape />,
        },
        {
            value: 1440,
            icon: <IconLaptop />,
        },
        {
            value: 1920,
            icon: <IconLaptop />,
        },
    ]

    // Let's add current width as an option if it's not in the list
    const allOptions = [...options]
    if (widthOverride && !options.some((option) => option.value === widthOverride)) {
        allOptions.push({
            value: widthOverride,
            icon: <IconLaptop />,
        })
    }

    return (
        <div className="flex justify-center items-center gap-2">
            <span>Screen width:</span>
            <LemonSelect
                size="small"
                onChange={setIframeWidth}
                value={widthOverride ? widthOverride : undefined}
                data-attr="viewport-chooser"
                options={allOptions.map(({ value, icon }) => ({
                    value,
                    label: (
                        <div className="flex items-center gap-1">
                            {icon}
                            <div className="text-xs">{value} px</div>
                        </div>
                    ),
                }))}
            />
        </div>
    )
}

/**
 * values and actions are passed as props because they are different
 * between fixed and embedded mode
 */
export function FilterPanel(): JSX.Element {
    const [isSettingsOpen, setIsSettingsOpen] = useState(false)
    const {
        heatmapFilters,
        heatmapColorPalette,
        heatmapFixedPositionMode,
        viewportRange,
        commonFilters,
        rawHeatmapLoading,
        heatmapEmpty,
    } = useValues(heatmapDataLogic({ context: 'in-app' }))

    const { patchHeatmapFilters, setHeatmapColorPalette, setHeatmapFixedPositionMode, setCommonFilters } = useActions(
        heatmapDataLogic({ context: 'in-app' })
    )

    const debouncedLoading = useDebounceLoading(rawHeatmapLoading ?? false)

    // KLUDGE: the loading bar flaps in visual regression tests,
    // for some reason our wait for loading to finish can't see it
    // this is ugly but better than stopping taking visual snapshots of it
    return (
        <>
            {debouncedLoading && !inStorybook() && !inStorybookTestRunner() && (
                <LoadingBar
                    wrapperClassName="absolute top-0 left-0 w-full overflow-hidden rounded-none my-0"
                    className="h-1 rounded-none"
                />
            )}
            <div className="flex-none md:flex justify-between items-center gap-2 my-2">
                <div className="flex-none md:flex items-center gap-2 my-2 md:my-0">
                    <DateFilter
                        dateFrom={commonFilters?.date_from}
                        dateTo={commonFilters?.date_to}
                        onChange={(fromDate, toDate) => {
                            setCommonFilters?.({ ...commonFilters, date_from: fromDate, date_to: toDate })
                        }}
                        dateOptions={heatmapDateOptions}
                    />
                    <div className="mt-2 md:mt-0">
                        <Popover
                            overlay={
                                <div className="p-2">
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
                            }
                            visible={isSettingsOpen}
                            onClickOutside={() => {
                                setIsSettingsOpen(false)
                            }}
                            placement="bottom"
                        >
                            <LemonButton
                                type="secondary"
                                size="small"
                                onClick={() => setIsSettingsOpen(!isSettingsOpen)}
                                icon={<IconGear />}
                                tooltip="Heatmap settings"
                                data-attr="heatmap-settings"
                            >
                                Heatmap settings
                            </LemonButton>
                        </Popover>
                    </div>
                </div>
                <div className="flex items-center gap-2 flex-wrap">
                    <ViewportChooser />
                    <div className="flex items-center gap-2">
                        <TestAccountFilter
                            size="small"
                            filters={{ filter_test_accounts: commonFilters?.filter_test_accounts }}
                            onChange={(value) => {
                                setCommonFilters?.({
                                    ...commonFilters,
                                    filter_test_accounts: value.filter_test_accounts,
                                })
                            }}
                        />
                    </div>
                </div>
            </div>
            {heatmapEmpty ? (
                <LemonBanner type="info" className="mb-2">
                    No data found. Try changing your filters or the URL above.
                </LemonBanner>
            ) : null}
        </>
    )
}
