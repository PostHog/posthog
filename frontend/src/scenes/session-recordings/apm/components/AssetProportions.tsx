import { Tooltip } from '@posthog/lemon-ui'

import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import { humanizeBytes } from 'lib/utils'
import { assetTypeToColor } from 'scenes/session-recordings/apm/performance-event-utils'
import { AssetSizeInfo } from 'scenes/session-recordings/apm/performanceEventDataLogic'

import { AssetType } from '~/types'

interface AssetProportionsProps {
    data: Record<string, AssetSizeInfo>
}

const AssetProportions = ({ data }: AssetProportionsProps): JSX.Element => {
    const totalBytes = Object.values(data).reduce((acc, item) => acc + (item.bytes || 0), 0)

    return (
        <div className="flex flex-col deprecated-space-y-2 w-full">
            <h3 className="mb-0">Asset breakdown</h3>
            <div className="flex flex-row w-full deprecated-space-x-1 items-center">
                {Object.entries(data).map(([label, sizeInfo]) => {
                    return <Asset key={label} label={label} bytes={sizeInfo.bytes} totalBytes={totalBytes} />
                })}
            </div>
        </div>
    )
}

const Asset = ({
    label,
    bytes,
    totalBytes,
}: {
    label: string
    bytes: number
    totalBytes: number
}): JSX.Element | null => {
    const { ref: wrapperRef, size: display } = useResizeBreakpoints({
        0: 'invisible',
        100: 'visible',
    })

    if (bytes === 0) {
        return null
    }
    const proportion = (bytes / totalBytes) * 100
    const bgColor = assetTypeToColor(label as AssetType)

    const content = (
        <div className="flex flex-col items-center justify-center text-xs">
            <div className="font-bold">{label}</div>
            <div className="">
                {humanizeBytes(bytes)} ({proportion.toFixed(2)}%)
            </div>
        </div>
    )

    return (
        <Tooltip delayMs={0} title={display === 'invisible' ? content : undefined}>
            <div
                ref={wrapperRef}
                key={label}
                className="h-12 flex justify-center px-2 py-1 rounded-xs"
                /* eslint-disable-next-line react/forbid-dom-props */
                style={{
                    width: `${proportion}%`,
                    backgroundColor: bgColor,
                }}
            >
                {display === 'visible' && content}
            </div>
        </Tooltip>
    )
}

export default AssetProportions
