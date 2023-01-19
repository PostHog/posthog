import { Menu } from 'antd'
import { ClockCircleOutlined } from '@ant-design/icons'

import { LemonButton } from '@posthog/lemon-ui'
import { IconTrendingFlat, IconTrendingFlatDown } from 'lib/components/icons'
import { humanFriendlyDuration } from 'lib/utils'

import { pathsLogicType } from './pathsLogicType'

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
        <Menu
            style={{
                marginTop: -5,
                border: '1px solid var(--border)',
                borderRadius: '0px 0px 4px 4px',
                width: 200,
            }}
        >
            {!isPathEnd && (
                <div className="text-xs flex items-center p-2 gap-2">
                    <IconTrendingFlat className="text-xl shrink-0 text-success" />
                    <span>Continuing</span>
                    <LemonButton size="small" onClick={() => openPersonsModal({ path_start_key: name })}>
                        <span className="text-xs">
                            {continuingCount}
                            <span className="text-muted-alt ml-2">({continuingPercentage}%)</span>
                        </span>
                    </LemonButton>
                </div>
            )}
            {dropOffCount > 0 && (
                <div className="text-xs flex items-center p-2 gap-2 border-t">
                    <IconTrendingFlatDown className="text-xl shrink-0 text-danger" />
                    <span>Dropping off</span>
                    <LemonButton size="small" onClick={() => openPersonsModal({ path_dropoff_key: name })}>
                        <span className="text-xs">
                            {dropOffCount}
                            <span className="text-muted-alt text-xs ml-2">({dropoffPercentage}%)</span>
                        </span>
                    </LemonButton>
                </div>
            )}
            {!isPathStart && (
                <div className="text-xs flex items-center p-2 gap-2 border-t">
                    <ClockCircleOutlined style={{ color: 'var(--muted)', fontSize: 16 }} />
                    <span>
                        Average time from previous step <b>{humanFriendlyDuration(averageConversionTime)}</b>
                    </span>
                </div>
            )}
        </Menu>
    )
}
