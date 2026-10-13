import { useValues } from 'kea'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { playerMetaLogic } from 'scenes/session-recordings/player/player-meta/playerMetaLogic'

import { sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'
import { PlayerSidebarOverviewRows } from './PlayerSidebarOverviewRows'

export function PlayerSidebarOverviewDeviceTab(): JSX.Element {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const { overviewItemsByTab, resolution, scale, resolutionDisplay, scaleDisplay, locationDisplay, loading } =
        useValues(playerMetaLogic(logicProps))

    // Pixel sizes instead of CSS aspect-ratio, so unknown or extreme resolutions still draw as a screen.
    const aspect = resolution && resolution.width > 0 ? resolution.height / resolution.width : 10 / 16
    const frameWidth = aspect > 1 ? Math.round(56 / aspect) : 80
    const frameHeight = aspect > 1 ? 56 : Math.round(80 * Math.min(Math.max(aspect, 0.45), 0.8))
    const visiblePercent = Math.round(Math.min(Math.max(scale, 0), 1) * 80)

    return (
        <>
            <div className="rounded border bg-surface-primary px-2 py-2 flex flex-row items-center gap-3 min-w-0">
                {loading ? (
                    <LemonSkeleton className="h-10 w-full" />
                ) : (
                    <>
                        <Tooltip
                            title={
                                <>
                                    The page was captured at <b>{resolutionDisplay}</b>. The dashed box is the part you
                                    see at <b>{scaleDisplay}</b> of the original size.
                                </>
                            }
                        >
                            <div className="flex flex-col items-center shrink-0 pb-1">
                                <div
                                    className="relative rounded border-2 bg-surface-secondary"
                                    // eslint-disable-next-line react/forbid-dom-props
                                    style={{ width: frameWidth, height: frameHeight }}
                                >
                                    <div
                                        className="absolute left-1 top-1 rounded-xs border border-dashed border-accent bg-surface-primary"
                                        // eslint-disable-next-line react/forbid-dom-props
                                        style={{ width: `${visiblePercent}%`, height: `${visiblePercent}%` }}
                                    />
                                </div>
                                <div className="h-1.5 w-8 rounded-b-sm bg-muted" />
                            </div>
                        </Tooltip>
                        <div className="flex flex-col min-w-0 text-xs">
                            <span className="font-medium tabular-nums truncate">{resolutionDisplay}</span>
                            <span className="text-secondary tabular-nums truncate">viewing at {scaleDisplay}</span>
                            {locationDisplay && <span className="font-medium truncate">{locationDisplay}</span>}
                        </div>
                    </>
                )}
            </div>
            <PlayerSidebarOverviewRows
                items={overviewItemsByTab.device}
                pickerGroupType={TaxonomicFilterGroupType.SessionProperties}
            />
        </>
    )
}
