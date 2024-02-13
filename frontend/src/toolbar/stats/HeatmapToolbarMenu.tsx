import { useActions, useValues } from 'kea'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { IconSync } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { ToolbarMenu } from '~/toolbar/bar/ToolbarMenu'
import { elementsLogic } from '~/toolbar/elements/elementsLogic'
import { heatmapLogic } from '~/toolbar/elements/heatmapLogic'
import { currentPageLogic } from '~/toolbar/stats/currentPageLogic'

export const HeatmapToolbarMenu = (): JSX.Element => {
    const { wildcardHref } = useValues(currentPageLogic)
    const { setWildcardHref } = useActions(currentPageLogic)

    const { matchLinksByHref, countedElements, clickCount, heatmapLoading, heatmapFilter, canLoadMoreElementStats } =
        useValues(heatmapLogic)
    const { setHeatmapFilter, loadMoreElementStats, setMatchLinksByHref } = useActions(heatmapLogic)
    const { setHighlightElement, setSelectedElement } = useActions(elementsLogic)

    return (
        <ToolbarMenu>
            <ToolbarMenu.Header>
                <LemonInput value={wildcardHref} onChange={setWildcardHref} />
                <div className="space-y-1 border-b px-1 pb-2">
                    <div className="text-muted p-1">Use * as a wildcard</div>
                    <div className="flex flex-row items-center space-x-2">
                        <DateFilter
                            dateFrom={heatmapFilter.date_from ?? '-7d'}
                            dateTo={heatmapFilter.date_to}
                            onChange={(date_from, date_to) => setHeatmapFilter({ date_from, date_to })}
                        />

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

                        {heatmapLoading ? <Spinner /> : null}
                    </div>
                    <div>
                        Found: {countedElements.length} elements / {clickCount} clicks!
                    </div>

                    <Tooltip title="Matching links by their target URL can exclude clicks from the heatmap if the URL is too unique.">
                        <LemonSwitch
                            checked={matchLinksByHref}
                            label="Match links by their target URL"
                            onChange={(checked) => setMatchLinksByHref(checked)}
                            fullWidth={true}
                            bordered={true}
                        />
                    </Tooltip>
                </div>
            </ToolbarMenu.Header>
            <ToolbarMenu.Body>
                <div className="flex flex-col space-y-2">
                    <div className="flex flex-col w-full h-full">
                        {heatmapLoading ? (
                            <span className="flex-1 flex justify-center items-center p-4">
                                <Spinner className="text-2xl" />
                            </span>
                        ) : countedElements.length ? (
                            countedElements.map(({ element, count, actionStep }, index) => {
                                return (
                                    <div
                                        className="p-2 flex flex-row justify-between cursor-pointer hover:bg-primary-highlight"
                                        key={index}
                                        onClick={() => setSelectedElement(element)}
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
                                )
                            })
                        ) : (
                            <div className="p-2">No elements found.</div>
                        )}
                    </div>
                </div>
            </ToolbarMenu.Body>
        </ToolbarMenu>
    )
}
