import { IconInfo } from '@posthog/icons'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonSegmentedButton } from 'lib/lemon-ui/LemonSegmentedButton'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { humanFriendlyNumber } from 'lib/utils'

import { UniqueUsersPanel } from './components'
import { ConversionRateInputType } from './runningTimeCalculatorLogic'

type FunnelMetricDataPanelProps = {
    uniqueUsers: number
    conversionRateInputType: ConversionRateInputType
    automaticConversionRateDecimal: number
    manualConversionRate: number
    onChangeType: (type: ConversionRateInputType) => void
    onChangeManualConversionRate: (rate: number) => void
}

export const FunnelMetricDataPanel = ({
    uniqueUsers,
    conversionRateInputType,
    automaticConversionRateDecimal,
    manualConversionRate,
    onChangeType,
    onChangeManualConversionRate,
}: FunnelMetricDataPanelProps): JSX.Element => {
    return (
        <div>
            <div className="grid grid-cols-3 gap-4">
                <UniqueUsersPanel uniqueUsers={uniqueUsers ?? 0} />
                <div>
                    <div className="card-secondary">
                        <span>Conversion rate input</span>
                        <Tooltip
                            className="ml-1"
                            title={
                                <>
                                    <strong>Automatic:</strong> Uses historical conversion rate between your exposure
                                    event and the conversion event. It may not always be representative of expected
                                    performance.
                                    <br />
                                    <br />
                                    <strong>Manual:</strong> Allows you to set a custom conversion rate based on your
                                    own knowledge of the funnel.
                                </>
                            }
                        >
                            <IconInfo className="text-secondary ml-1" />
                        </Tooltip>
                    </div>
                    <LemonSegmentedButton
                        className="mt-2"
                        size="small"
                        options={[
                            {
                                label: 'Manual',
                                value: ConversionRateInputType.MANUAL,
                            },
                            {
                                label: 'Automatic',
                                value: ConversionRateInputType.AUTOMATIC,
                            },
                        ]}
                        value={conversionRateInputType}
                        onChange={(value) => {
                            onChangeType(value as ConversionRateInputType)
                        }}
                    />
                    {conversionRateInputType === ConversionRateInputType.MANUAL && (
                        <div className="flex items-center gap-2">
                            <LemonInput
                                className="w-[80px] mt-2"
                                min={0}
                                step={1}
                                max={100}
                                type="number"
                                value={manualConversionRate || undefined}
                                onChange={(newValue) => {
                                    if (newValue !== null && newValue !== undefined && newValue >= 0) {
                                        onChangeManualConversionRate(newValue)
                                    }
                                }}
                            />
                            <div>%</div>
                        </div>
                    )}
                    {conversionRateInputType === ConversionRateInputType.AUTOMATIC && (
                        <div className="font-semibold mt-2">
                            ~{humanFriendlyNumber(automaticConversionRateDecimal * 100, 2)}%
                        </div>
                    )}
                </div>
            </div>
        </div>
    )
}
