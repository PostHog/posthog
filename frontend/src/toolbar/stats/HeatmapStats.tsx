import { useActions, useValues } from 'kea'
import { List, Space } from 'antd'
import { heatmapLogic } from '~/toolbar/elements/heatmapLogic'
import { elementsLogic } from '~/toolbar/elements/elementsLogic'
import { getShadowRootPopupContainer } from '~/toolbar/utils'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { Spinner } from 'lib/components/Spinner/Spinner'
import { LemonInput } from 'lib/components/LemonInput/LemonInput'
import { currentPageLogic } from '~/toolbar/stats/currentPageLogic'
import { LemonButton } from 'lib/components/LemonButton'
import { IconSync } from 'lib/components/icons'
import { AlertMessage } from 'lib/components/AlertMessage'

export function HeatmapStats(): JSX.Element {
    const { countedElements, clickCount, heatmapEnabled, heatmapLoading, heatmapFilter, canLoadMoreElementStats } =
        useValues(heatmapLogic)
    const { setHeatmapFilter, loadMoreElementStats } = useActions(heatmapLogic)
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
                            onClick={() => loadMoreElementStats()}
                            disabled={!canLoadMoreElementStats}
                        >
                            Load more
                        </LemonButton>
                        {canLoadMoreElementStats ? null : (
                            <AlertMessage type={'info'} className={'pt-2'}>
                                Loaded all elements in this data range.
                            </AlertMessage>
                        )}
                    </div>
                    <List
                        itemLayout="horizontal"
                        dataSource={countedElements}
                        renderItem={({ element, count, actionStep }, index) => (
                            <List.Item
                                onClick={() => setSelectedElement(element)}
                                onMouseEnter={() => setHighlightElement(element)}
                                onMouseLeave={() => setHighlightElement(null)}
                                style={{ cursor: 'pointer' }}
                            >
                                <List.Item.Meta
                                    title={
                                        <Space>
                                            <span
                                                style={{
                                                    display: 'inline-block',
                                                    width: Math.floor(Math.log10(countedElements.length) + 1) * 12 + 6,
                                                    textAlign: 'right',
                                                    marginRight: 4,
                                                }}
                                            >
                                                {index + 1}.
                                            </span>
                                            {actionStep?.text ||
                                                (actionStep?.tag_name ? (
                                                    <code>&lt;{actionStep.tag_name}&gt;</code>
                                                ) : (
                                                    <em>Element</em>
                                                ))}
                                        </Space>
                                    }
                                />
                                <div>{count} clicks</div>
                            </List.Item>
                        )}
                    />
                </div>
            ) : null}
        </div>
    )
}
