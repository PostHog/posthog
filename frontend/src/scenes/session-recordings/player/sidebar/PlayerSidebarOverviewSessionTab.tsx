import clsx from 'clsx'
import { useValues } from 'kea'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { OVERVIEW_STAT_LABELS } from 'scenes/session-recordings/player/player-meta/overviewTabs'
import { playerMetaLogic } from 'scenes/session-recordings/player/player-meta/playerMetaLogic'

import { OverviewItem } from '../../components/OverviewGrid'
import { sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'
import { PlayerSidebarOverviewRows } from './PlayerSidebarOverviewRows'

export function PlayerSidebarOverviewSessionTab(): JSX.Element {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const { overviewItemsByTab, loading } = useValues(playerMetaLogic(logicProps))

    const isStat = (item: OverviewItem): boolean => item.type === 'text' && OVERVIEW_STAT_LABELS.includes(item.label)
    const statItems = overviewItemsByTab.session.filter(isStat)
    const rowItems = overviewItemsByTab.session.filter((item) => !isStat(item))

    return (
        <>
            {statItems.length > 0 && (
                <div className="rounded border bg-surface-primary flex flex-row justify-between px-2 py-1.5 gap-2">
                    {loading
                        ? statItems.map((item) => <LemonSkeleton key={item.label} className="h-8 flex-1" />)
                        : statItems.map((item) => {
                              const isErrorCount = item.label === 'Errors' && Number(item.value) > 0
                              return (
                                  <Tooltip key={item.label} title={item.keyTooltip}>
                                      <div className="flex flex-col items-center min-w-0 flex-1">
                                          <span
                                              className={clsx(
                                                  'font-semibold tabular-nums truncate max-w-full',
                                                  isErrorCount && 'text-danger'
                                              )}
                                          >
                                              {item.value}
                                          </span>
                                          <span className="text-xs text-secondary truncate max-w-full">
                                              {item.label}
                                          </span>
                                      </div>
                                  </Tooltip>
                              )
                          })}
                </div>
            )}
            <PlayerSidebarOverviewRows items={rowItems} pickerGroupType={TaxonomicFilterGroupType.SessionProperties} />
        </>
    )
}
