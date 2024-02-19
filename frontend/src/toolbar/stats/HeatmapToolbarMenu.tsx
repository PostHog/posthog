import { useActions, useValues } from 'kea'
import { CUSTOM_OPTION_KEY } from 'lib/components/DateFilter/types'
import { IconSync } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
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

    const { matchLinksByHref, countedElements, clickCount, heatmapLoading, heatmapFilter, canLoadMoreElementStats } =
        useValues(heatmapLogic)
    const { setHeatmapFilter, loadMoreElementStats, setMatchLinksByHref } = useActions(heatmapLogic)
    const { setHighlightElement, setSelectedElement } = useActions(elementsLogic)

    const dateItems = dateMapping
        .filter((dm) => dm.key !== CUSTOM_OPTION_KEY)
        .map((dateOption) => ({
            label: dateOption.key,
            onClick: () => setHeatmapFilter({ date_from: dateOption.values[0], date_to: dateOption.values[1] }),
        }))

    return (
        <ToolbarMenu>
            <ToolbarMenu.Header>
                <LemonInput value={wildcardHref} onChange={setWildcardHref} />
                <div className="space-y-1 border-b px-1 pb-2">
                    <div className="text-muted p-1">Use * as a wildcard</div>
                    <div className="flex flex-row items-center space-x-2">
                        <LemonMenu items={dateItems}>
                            <LemonButton size="small" type="secondary">
                                {dateFilterToText(heatmapFilter.date_from, heatmapFilter.date_to, 'Last 7 days')}
                            </LemonButton>
                        </LemonMenu>

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
                        <div>
                            <LemonSwitch
                                checked={matchLinksByHref}
                                label="Match links by their target URL"
                                onChange={(checked) => setMatchLinksByHref(checked)}
                                fullWidth={true}
                                bordered={true}
                            />
                        </div>
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
