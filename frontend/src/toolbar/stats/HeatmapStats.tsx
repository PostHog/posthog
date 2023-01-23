import { useActions, useValues } from 'kea'
import { heatmapLogic } from '~/toolbar/elements/heatmapLogic'
import { elementsLogic } from '~/toolbar/elements/elementsLogic'
import { getShadowRootPopupContainer } from '~/toolbar/utils'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { Spinner } from 'lib/components/Spinner/Spinner'
import { LemonInput } from 'lib/components/LemonInput/LemonInput'
import { currentPageLogic } from '~/toolbar/stats/currentPageLogic'
import { LemonButton } from 'lib/components/LemonButton'
import { IconSync } from 'lib/components/icons'
import { LemonSwitch } from 'lib/components/LemonSwitch/LemonSwitch'
import { Tooltip } from 'lib/components/Tooltip'
import './HeatmapStat.scss'

export function HeatmapStats(): JSX.Element {
    const {
        matchLinksByHref,
        countedElements,
        clickCount,
        heatmapEnabled,
        heatmapLoading,
        heatmapFilter,
        canLoadMoreElementStats,
    } = useValues(heatmapLogic)
    const { setHeatmapFilter, loadMoreElementStats, setMatchLinksByHref } = useActions(heatmapLogic)
    const { setHighlightElement, setSelectedElement } = useActions(elementsLogic)
    const { wildcardHref } = useValues(currentPageLogic)
    const { setWildcardHref } = useActions(currentPageLogic)

    return (
        <div className="m-4">
            {heatmapEnabled ? (
                <div className="space-y-2">
                    <div>
                        <LemonInput value={wildcardHref} onChange={setWildcardHref} />
                        <div className="text-muted">Use * as a wildcard</div>
                    </div>
                    <div className="flex items-center gap-2">
                        <DateFilter
                            dateFrom={heatmapFilter.date_from ?? '-7d'}
                            dateTo={heatmapFilter.date_to}
                            onChange={(date_from, date_to) => setHeatmapFilter({ date_from, date_to })}
                            getPopupContainer={getShadowRootPopupContainer}
                        />

                        {heatmapLoading ? <Spinner /> : null}
                    </div>
                    <div>
                        Found: {countedElements.length} elements / {clickCount} clicks!
                    </div>
                    <div>
                        <LemonButton
                            icon={<IconSync />}
                            type={'secondary'}
                            status={'primary-alt'}
                            size={'small'}
                            onClick={loadMoreElementStats}
                            disabledReason={
                                canLoadMoreElementStats ? undefined : 'Loaded all elements in this data range.'
                            }
                            getPopupContainer={getShadowRootPopupContainer}
                        >
                            Load more
                        </LemonButton>
                    </div>

                    <Tooltip
                        title={
                            'Matching links by their target URL can exclude clicks from the heatmap if the URL is too unique.'
                        }
                        getPopupContainer={getShadowRootPopupContainer}
                    >
                        <div>
                            <LemonSwitch
                                checked={matchLinksByHref}
                                label={'Match links by their target URL'}
                                onChange={(checked) => setMatchLinksByHref(checked)}
                                fullWidth={true}
                                bordered={true}
                            />
                        </div>
                    </Tooltip>
                    <div className="flex flex-col w-full">
                        {countedElements.map(({ element, count, actionStep }, index) => {
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
                        })}
                    </div>
                </div>
            ) : null}
        </div>
    )
}
