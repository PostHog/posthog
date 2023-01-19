import { LemonButton } from '@posthog/lemon-ui'
import { IconTrendingFlat, IconTrendingFlatDown, IconSchedule } from 'lib/components/icons'
import { humanFriendlyDuration } from 'lib/utils'

import { pathsLogicType } from './pathsLogicType'
import { PATH_NODE_CARD_WIDTH } from './constants'

type PathNodeCardMenuProps = {
    name: string
    count: number
    continuingCount: number
    dropOffCount: number
    averageConversionTime: number | null
    isPathEnd: boolean
    isPathStart: boolean
    openPersonsModal: pathsLogicType['actions']['openPersonsModal']
}

export function PathNodeCardMenu({
    name,
    count,
    continuingCount,
    dropOffCount,
    averageConversionTime,
    isPathEnd,
    isPathStart,
    openPersonsModal,
}: PathNodeCardMenuProps): JSX.Element {
    const continuingPercentage = ((continuingCount / count) * 100).toFixed(1)
    const dropoffPercentage = ((dropOffCount / count) * 100).toFixed(1)

    return (
        <div
            className="bg-white border rounded"
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                width: PATH_NODE_CARD_WIDTH,
            }}
        >
            {!isPathEnd && (
                <div className="text-xs flex items-center justify-between p-2 gap-2">
                    <div className="flex items-center gap-2">
                        <IconTrendingFlat className="text-xl shrink-0 text-success" />
                        <span>Continuing</span>
                    </div>
                    <LemonButton size="small" onClick={() => openPersonsModal({ path_start_key: name })}>
                        <span className="text-xs">
                            {continuingCount}
                            <span className="text-muted-alt ml-2">({continuingPercentage}%)</span>
                        </span>
                    </LemonButton>
                </div>
            )}
            {dropOffCount > 0 && (
                <div className="text-xs flex items-center justify-between p-2 gap-2 border-t border-dashed">
                    <div className="flex items-center gap-2">
                        <IconTrendingFlatDown className="text-xl shrink-0 text-danger" />
                        <span>Dropping off</span>
                    </div>
                    <LemonButton size="small" onClick={() => openPersonsModal({ path_dropoff_key: name })}>
                        <span className="text-xs">
                            {dropOffCount}
                            <span className="text-muted-alt text-xs ml-2">({dropoffPercentage}%)</span>
                        </span>
                    </LemonButton>
                </div>
            )}
            {!isPathStart && (
                <div className="text-xs flex items-center justify-between p-2 gap-2 border-t border-dashed">
                    <div className="flex items-center gap-2">
                        <IconSchedule className="text-xl shrink-0 text-muted" />
                        <span>Average time from previous step</span>
                    </div>
                    <b className="pr-2">{humanFriendlyDuration(averageConversionTime)}</b>
                </div>
            )}
        </div>
    )
}
