import { humanizeBytes } from 'lib/utils'
import { assetTypeToColor } from 'scenes/session-recordings/apm/performance-event-utils'
import { AssetSizeInfo } from 'scenes/session-recordings/apm/performanceEventDataLogic'

interface AssetProportionsProps {
    data: Record<string, AssetSizeInfo>
}

const AssetProportions = ({ data }: AssetProportionsProps): JSX.Element => {
    const totalBytes = Object.values(data).reduce((acc, item) => acc + (item.bytes || 0), 0)

    return (
        <div className="flex flex-col space-y-2 w-full">
            <h3 className="mb-0">Asset breakdown</h3>
            <div className="flex flex-row w-full space-x-1 items-center">
                {Object.entries(data).map(([label, sizeInfo]) => {
                    if (sizeInfo.bytes === 0) {
                        return null
                    }
                    const proportion = (sizeInfo.bytes / totalBytes) * 100
                    const bgColor = assetTypeToColor[label]
                    return (
                        <div
                            key={label}
                            className="items-center px-2 py-1 text-xs border flex flex-col"
                            /* eslint-disable-next-line react/forbid-dom-props */
                            style={{
                                width: `${proportion}%`,
                                backgroundColor: bgColor,
                            }}
                        >
                            <div>{label}</div>
                            <div>{humanizeBytes(sizeInfo.bytes)}</div>({proportion.toFixed(2)}%)
                        </div>
                    )
                })}
            </div>
        </div>
    )
}

export default AssetProportions
