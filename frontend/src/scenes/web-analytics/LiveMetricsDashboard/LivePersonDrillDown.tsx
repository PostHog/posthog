import { useActions, useValues } from 'kea'

import { IconInfo, IconRefresh } from '@posthog/icons'
import { LemonButton, LemonSkeleton, Tooltip } from '@posthog/lemon-ui'

import { LemonDrawer } from 'lib/lemon-ui/LemonDrawer/LemonDrawer'

import {
    LivePersonDrillDownBreakdownType,
    LivePersonDrillDownSelection,
    livePersonDrillDownDrawerLogic,
} from './livePersonDrillDownDrawerLogic'
import { livePersonDrillDownLogic } from './livePersonDrillDownLogic'
import { LivePersonDrillDownRow } from './LivePersonDrillDownRow'

const BREAKDOWN_TITLE_PREFIX: Record<LivePersonDrillDownBreakdownType, string> = {
    country: 'Visitors from',
    city: 'Visitors from',
    device: 'Visitors using',
    browser: 'Visitors using',
}

const LivePersonDrillDownInner = ({ selection }: { selection: LivePersonDrillDownSelection }): JSX.Element => {
    const { closeDrillDown } = useActions(livePersonDrillDownDrawerLogic)
    const logicProps = {
        breakdownType: selection.breakdownType,
        breakdownValue: selection.breakdownValue,
    }
    const {
        persons,
        personsLoading,
        totalCount,
        identifiedCount,
        anonymousCount,
        newVisitorCount,
        isTruncated,
        recordingCountByPersonKey,
    } = useValues(livePersonDrillDownLogic(logicProps))
    const { refresh } = useActions(livePersonDrillDownLogic(logicProps))

    const title = `${BREAKDOWN_TITLE_PREFIX[selection.breakdownType]} ${selection.breakdownLabel}`

    return (
        <LemonDrawer
            isOpen
            onClose={closeDrillDown}
            title={
                <div className="flex items-center gap-2 min-w-0">
                    <span className="truncate">{title}</span>
                    <span className="text-sm font-normal text-muted tabular-nums shrink-0">
                        {totalCount.toLocaleString()}
                    </span>
                </div>
            }
            description={
                <div className="flex items-center gap-1 text-xs text-muted">
                    Visitors in the last 30 minutes
                    <Tooltip title="Lists persons seen for this segment within the live dashboard's 30-minute window. The count updates live as new visitors arrive.">
                        <IconInfo className="text-sm" />
                    </Tooltip>
                </div>
            }
            footer={
                <LemonButton type="secondary" size="small" icon={<IconRefresh />} onClick={refresh}>
                    Refresh
                </LemonButton>
            }
            data-attr="live-person-drilldown"
        >
            <div className="flex flex-col gap-3">
                {newVisitorCount > 0 && (
                    <LemonButton
                        type="secondary"
                        size="small"
                        fullWidth
                        center
                        icon={<IconRefresh />}
                        onClick={refresh}
                        data-attr="live-person-drilldown-refresh-pill"
                    >
                        {newVisitorCount === 1
                            ? '1 new visitor — refresh'
                            : `${newVisitorCount.toLocaleString()} new visitors — refresh`}
                    </LemonButton>
                )}

                {personsLoading && persons.length === 0 ? (
                    <div className="flex flex-col gap-2">
                        {Array.from({ length: 6 }).map((_, i) => (
                            <LemonSkeleton key={i} className="h-10 w-full" />
                        ))}
                    </div>
                ) : identifiedCount === 0 && anonymousCount === 0 ? (
                    <div className="text-sm text-muted text-center py-8">No visitors in this window</div>
                ) : (
                    <>
                        {persons.length > 0 && (
                            <div className="flex flex-col">
                                <div className="text-xs font-semibold text-muted uppercase mb-2">
                                    Identified ({persons.length.toLocaleString()}
                                    {isTruncated ? ` of ${identifiedCount.toLocaleString()}` : ''})
                                </div>
                                <div className="flex flex-col">
                                    {persons.map((person) => {
                                        const key = person.id ?? person.uuid
                                        return (
                                            <LivePersonDrillDownRow
                                                key={key}
                                                person={person}
                                                recordingCount={key ? recordingCountByPersonKey[key] : undefined}
                                            />
                                        )
                                    })}
                                </div>
                                {isTruncated && (
                                    <div className="text-xs text-muted mt-2">
                                        Showing the {persons.length.toLocaleString()} most recently seen — narrow
                                        filters to see more.
                                    </div>
                                )}
                            </div>
                        )}

                        {persons.length === 0 && identifiedCount > 0 && !personsLoading && (
                            <div className="text-sm text-muted">
                                No profiles found for these distinct IDs. They may not have person processing enabled.
                            </div>
                        )}

                        {anonymousCount > 0 && (
                            <div className="flex flex-col gap-1 pt-2 border-t border-border">
                                <div className="text-xs font-semibold text-muted uppercase">Anonymous</div>
                                <Tooltip title="Cookieless visitors are tracked anonymously by IP and user agent. They do not have a person profile and cannot be linked to.">
                                    <div className="text-sm text-muted">
                                        {anonymousCount === 1
                                            ? '1 anonymous visitor — no profile linked'
                                            : `${anonymousCount.toLocaleString()} anonymous visitors — no profile linked`}
                                    </div>
                                </Tooltip>
                            </div>
                        )}
                    </>
                )}
            </div>
        </LemonDrawer>
    )
}

export const LivePersonDrillDown = (): JSX.Element | null => {
    const { currentSelection } = useValues(livePersonDrillDownDrawerLogic)
    if (!currentSelection) {
        return null
    }
    return (
        <LivePersonDrillDownInner
            // Re-mount when the (type, value) tuple changes so the keyed logic instance switches cleanly.
            key={`${currentSelection.breakdownType}:${currentSelection.breakdownValue}`}
            selection={currentSelection}
        />
    )
}
