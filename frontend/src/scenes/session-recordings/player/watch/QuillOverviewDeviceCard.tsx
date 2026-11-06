import { useValues } from 'kea'

import { Skeleton, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { playerMetaLogic } from 'scenes/session-recordings/player/player-meta/playerMetaLogic'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { QuillOverviewRows } from './QuillOverviewRows'

export function QuillOverviewDeviceCard(): JSX.Element {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const { overviewItemsByTab, resolution, scale, resolutionDisplay, scaleDisplay, locationDisplay, loading } =
        useValues(playerMetaLogic(logicProps))

    // Pixel sizes instead of CSS aspect-ratio, so unknown or extreme resolutions still draw as a screen.
    const aspect = resolution && resolution.width > 0 ? resolution.height / resolution.width : 10 / 16
    const frameWidth = aspect > 1 ? Math.round(56 / aspect) : 88
    const frameHeight = aspect > 1 ? 56 : Math.round(88 * Math.min(Math.max(aspect, 0.5), 0.65))
    const visiblePercent = Math.round(Math.min(Math.max(scale, 0), 1) * 80)

    return (
        <>
            <div className="rounded border border-border bg-card px-2 py-2.5 flex items-center gap-3 min-w-0">
                {loading ? (
                    <Skeleton className="h-10 w-full" />
                ) : (
                    <>
                        <Tooltip>
                            <TooltipTrigger render={<span className="flex flex-col items-center shrink-0 pb-1" />}>
                                <span
                                    className="relative block rounded border-2 border-border bg-muted"
                                    // eslint-disable-next-line react/forbid-dom-props
                                    style={{ width: frameWidth, height: frameHeight }}
                                >
                                    <span
                                        className="absolute left-1 top-1 block rounded-xs border border-dashed border-primary bg-card"
                                        // eslint-disable-next-line react/forbid-dom-props
                                        style={{ width: `${visiblePercent}%`, height: `${visiblePercent}%` }}
                                    />
                                </span>
                                <span className="block h-1.5 w-9 rounded-b-sm bg-border" />
                            </TooltipTrigger>
                            <TooltipContent className="max-w-72">
                                The page was captured at <b>{resolutionDisplay}</b>. The dashed box is the part you see
                                at <b>{scaleDisplay}</b> of the original size.
                            </TooltipContent>
                        </Tooltip>
                        <div className="flex flex-col min-w-0 text-xs">
                            <span className="font-medium tabular-nums truncate">{resolutionDisplay}</span>
                            <span className="text-muted-foreground tabular-nums truncate">
                                viewing at {scaleDisplay}
                            </span>
                            {locationDisplay && <span className="font-medium truncate">{locationDisplay}</span>}
                        </div>
                    </>
                )}
            </div>
            <QuillOverviewRows
                items={overviewItemsByTab.device}
                pickerGroupType={TaxonomicFilterGroupType.SessionProperties}
            />
        </>
    )
}
