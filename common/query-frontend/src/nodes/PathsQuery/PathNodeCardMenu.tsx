import { MouseEventHandler } from 'react'

import { IconClock } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { IconTrendingFlat, IconTrendingFlatDown } from 'lib/lemon-ui/icons'
import { humanFriendlyDuration } from 'lib/utils'

import { PATH_NODE_CARD_WIDTH } from './constants'
import { pathsDataLogicType } from './pathsDataLogicType'

type PathNodeCardMenuProps = {
    name: string
    count: number
    continuingCount: number
    dropOffCount: number
    averageConversionTime: number | null
    isPathEnd: boolean
    isPathStart: boolean
    openPersonsModal: pathsDataLogicType['actions']['openPersonsModal']
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

    const openContinuingPersons = (): void => openPersonsModal({ path_start_key: name })
    const openDroppingPersons = (): void => openPersonsModal({ path_dropoff_key: name })

    return (
        <div
            // eslint-disable-next-line react/forbid-dom-props
            style={{ width: PATH_NODE_CARD_WIDTH }}
        >
            {!isPathEnd && (
                <CardItem
                    icon={<IconTrendingFlat className="text-xl shrink-0 text-success" />}
                    text="Continuing"
                    count={
                        <CountButton
                            onClick={openContinuingPersons}
                            count={continuingCount}
                            percentage={continuingPercentage}
                        />
                    }
                    border={false}
                />
            )}
            {dropOffCount > 0 && (
                <CardItem
                    icon={<IconTrendingFlatDown className="text-xl shrink-0 text-danger" />}
                    text="Dropping off"
                    count={
                        <CountButton
                            onClick={openDroppingPersons}
                            count={dropOffCount}
                            percentage={dropoffPercentage}
                        />
                    }
                />
            )}
            {!isPathStart && (
                <CardItem
                    icon={<IconClock className="text-xl shrink-0 text-secondary" />}
                    text="Average time from previous step"
                    count={<b className="pr-2">{humanFriendlyDuration(averageConversionTime)}</b>}
                />
            )}
        </div>
    )
}

type CountButtonProps = {
    count: string | number
    percentage: string | number
    onClick: MouseEventHandler<HTMLElement>
}

function CountButton({ count, percentage, onClick }: CountButtonProps): JSX.Element {
    return (
        <LemonButton size="small" onClick={onClick}>
            <span className="text-xs">
                {count}
                <span className="text-secondary ml-2">({percentage}%)</span>
            </span>
        </LemonButton>
    )
}

type CardItemProps = {
    icon: JSX.Element
    text: string
    count: JSX.Element
    border?: boolean
}

function CardItem({ icon, text, count, border = true }: CardItemProps): JSX.Element {
    return (
        <div className={`text-xs flex items-center justify-between p-2 gap-2 ${border && 'border-t border-dashed'}`}>
            <div className="flex items-center gap-2">
                {icon}
                <span>{text}</span>
            </div>
            {count}
        </div>
    )
}
