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

export const HeatmapToolbarMenu = (): JSX.Element => {
    const { wildcardHref } = useValues(currentPageLogic)
    const { setWildcardHref } = useActions(currentPageLogic)

    const {
        matchLinksByHref,
        countedElements,
        clickCount,
        heatmapFilter,
        canLoadMoreElementStats,
        heatmapFilterViewportFuzziness,
        viewportRange,
        rawHeatmapLoading,
        elementStatsLoading,
    } = useValues(heatmapLogic)
    const { patchHeatmapFilter, loadMoreElementStats, setMatchLinksByHref, setHeatmapFilterViewportFuzziness } =
        useActions(heatmapLogic)
    const { setHighlightElement, setSelectedElement } = useActions(elementsLogic)

    const dateItems = dateMapping
        .filter((dm) => dm.key !== CUSTOM_OPTION_KEY)
        .map((dateOption) => ({
            label: dateOption.key,
            onClick: () => patchHeatmapFilter({ date_from: dateOption.values[0], date_to: dateOption.values[1] }),
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
                            {dateFilterToText(heatmapFilter.date_from, heatmapFilter.date_to, 'Last 7 days')}
                        </LemonButton>
                    </LemonMenu>
                </div>
            </ToolbarMenu.Header>
            <ToolbarMenu.Body>
                <div className="border-b p-2">
                    <LemonSwitch
                        className="w-full"
                        checked={!!heatmapFilter.scrolldepth}
                        label="Scroll depth"
                        onChange={(e) =>
                            patchHeatmapFilter({
                                scrolldepth: e,
                            })
                        }
                    />

                    <p>TODO: Add notice about config settings required by checking their posthog-js version</p>
                </div>

                <div className="border-b p-2">
                    <LemonSwitch
                        className="w-full"
                        checked={!!heatmapFilter.heatmaps}
                        label={<>Heatmaps {rawHeatmapLoading ? <Spinner /> : null}</>}
                        onChange={(e) =>
                            patchHeatmapFilter({
                                heatmaps: e,
                            })
                        }
                    />

                    <p>Heatmaps are a blah blah blah</p>

                    {heatmapFilter.heatmaps && (
                        <>
                            <div className="space-y-2">
                                <div className="flex gap-2 justify-between items-center">
                                    <LemonLabel>Heatmap type</LemonLabel>
                                    <LemonSegmentedButton
                                        onChange={(e) => patchHeatmapFilter({ heatmap_type: e })}
                                        value={heatmapFilter.heatmap_type ?? undefined}
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
                                        ]}
                                        size="small"
                                    />
                                </div>

                                <div className="flex gap-2 justify-between items-center">
                                    <LemonLabel>Viewport width</LemonLabel>
                                    <LemonSlider
                                        className="flex-1"
                                        min={0}
                                        max={1}
                                        step={0.01}
                                        value={heatmapFilterViewportFuzziness}
                                        onChange={(value) => setHeatmapFilterViewportFuzziness(value)}
                                    />
                                    <Tooltip
                                        title={`
                                    The range of values 
                                    Heatmap will be loaded for all viewports where the width is above 

                                    `}
                                    >
                                        <code className="w-[6rem] text-right">{`${viewportRange.min} - ${viewportRange.max}`}</code>
                                    </Tooltip>
                                </div>
                            </div>
                        </>
                    )}
                </div>

                <div className="p-2">
                    <LemonSwitch
                        className="w-full"
                        checked={!!heatmapFilter.clickmaps}
                        label={<>Clickmaps (autocapture) {elementStatsLoading ? <Spinner /> : null}</>}
                        onChange={(e) =>
                            patchHeatmapFilter({
                                clickmaps: e,
                            })
                        }
                    />

                    <p>Clickmaps are a blah blah blah</p>

                    {heatmapFilter.clickmaps && (
                        <>
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

                            <div>
                                Found: {countedElements.length} elements / {clickCount} clicks!
                            </div>
                            <div className="flex flex-col w-full h-full">
                                {elementStatsLoading ? (
                                    <span className="flex-1 flex justify-center items-center p-4">
                                        <Spinner className="text-2xl" />
                                    </span>
                                ) : countedElements.length ? (
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
