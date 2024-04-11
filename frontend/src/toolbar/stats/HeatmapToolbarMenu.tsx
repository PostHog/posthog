import { IconMagicWand } from '@posthog/icons'
import { LemonCheckbox, LemonDialog, LemonDivider } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { capitalizeFirstLetter } from 'kea-forms'
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
    const { patchHeatmapFilter, loadMoreElementStats, setMatchLinksByHref } = useActions(heatmapLogic)
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

                <div className="border-b pt-2 pb-2">
                    <div className="space-y-2">
                        <div className="flex flex-row items-center gap-2 flex-wrap">
                            {['autocapture', 'clicks', 'rageclicks', 'mousemove'].map((action) => (
                                <LemonCheckbox
                                    key={action}
                                    size="small"
                                    bordered
                                    label={capitalizeFirstLetter(action)}
                                    checked={heatmapFilter.types.includes(action as any)}
                                    onChange={(checked) =>
                                        patchHeatmapFilter({
                                            types: (checked
                                                ? [...heatmapFilter.types, action]
                                                : heatmapFilter.types.filter((a) => a !== action)) as any[],
                                        })
                                    }
                                />
                            ))}
                        </div>
                        <div className="flex flex-row items-center gap-2">
                            <LemonMenu items={dateItems}>
                                <LemonButton size="small" type="secondary">
                                    {dateFilterToText(heatmapFilter.date_from, heatmapFilter.date_to, 'Last 7 days')}
                                </LemonButton>
                            </LemonMenu>

                            {heatmapLoading ? <Spinner /> : null}
                        </div>
                        <div>
                            Found: {countedElements.length} elements / {clickCount} clicks!
                        </div>
                    </div>

                    {heatmapFilter.types.includes('autocapture') && (
                        <>
                            <LemonDivider />
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
                        </>
                    )}
                </div>
            </ToolbarMenu.Header>
            <ToolbarMenu.Body>
                <div className="flex flex-col gap-2 my-2">
                    <div className="flex flex-col w-full h-full">
                        {heatmapLoading ? (
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
                </div>
            </ToolbarMenu.Body>
        </ToolbarMenu>
    )
}
