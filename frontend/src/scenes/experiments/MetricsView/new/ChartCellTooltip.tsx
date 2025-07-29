import { useState, useRef, useEffect } from 'react'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import {
    type ExperimentVariantResult,
    formatChanceToWin,
    formatPValue,
    getIntervalLabel,
    getVariantInterval,
    isBayesianResult,
} from '../shared/utils'

interface ChartCellTooltipProps {
    variantResult: ExperimentVariantResult
    children: React.ReactNode
}

export function ChartCellTooltip({ variantResult, children }: ChartCellTooltipProps): JSX.Element {
    const [isVisible, setIsVisible] = useState(false)
    const [tooltipPosition, setTooltipPosition] = useState({ x: 0, y: 0 })
    const containerRef = useRef<HTMLDivElement>(null)
    const tooltipRef = useRef<HTMLDivElement>(null)

    const interval = getVariantInterval(variantResult)
    const [lower, upper] = interval ? [interval[0], interval[1]] : [0, 0]
    const intervalPercent = interval ? `[${(lower * 100).toFixed(2)}%, ${(upper * 100).toFixed(2)}%]` : 'N/A'
    const intervalLabel = getIntervalLabel(variantResult)

    useEffect(() => {
        if (isVisible && containerRef.current && tooltipRef.current) {
            const containerRect = containerRef.current.getBoundingClientRect()
            const tooltipRect = tooltipRef.current.getBoundingClientRect()

            // Position tooltip centered above the container
            let x = containerRect.left + containerRect.width / 2 - tooltipRect.width / 2
            const y = containerRect.top - tooltipRect.height - 8

            // Keep tooltip within viewport bounds
            const padding = 8
            if (x < padding) {
                x = padding
            } else if (x + tooltipRect.width > window.innerWidth - padding) {
                x = window.innerWidth - tooltipRect.width - padding
            }

            setTooltipPosition({ x, y })
        }
    }, [isVisible])

    return (
        <div
            ref={containerRef}
            className="relative block w-full h-full"
            onMouseEnter={() => setIsVisible(true)}
            onMouseLeave={() => setIsVisible(false)}
        >
            {children}

            {isVisible && (
                <div
                    ref={tooltipRef}
                    className="fixed bg-bg-light border border-border px-3 py-2 rounded-md text-[13px] shadow-md z-[100] min-w-[280px]"
                    style={{
                        left: tooltipPosition.x,
                        top: tooltipPosition.y,
                        visibility: tooltipPosition.x === 0 ? 'hidden' : 'visible',
                    }}
                >
                    <div className="flex flex-col gap-1">
                        <div className="flex justify-between items-center">
                            <div className="font-semibold">{variantResult.key}</div>
                            {variantResult.key !== 'control' && (
                                <LemonTag
                                    type={
                                        !variantResult.significant
                                            ? 'muted'
                                            : (() => {
                                                  const interval = getVariantInterval(variantResult)
                                                  const deltaPercent = interval
                                                      ? ((interval[0] + interval[1]) / 2) * 100
                                                      : 0
                                                  return deltaPercent > 0 ? 'success' : 'danger'
                                              })()
                                    }
                                    size="small"
                                >
                                    {!variantResult.significant
                                        ? 'Not significant'
                                        : (() => {
                                              const interval = getVariantInterval(variantResult)
                                              const deltaPercent = interval
                                                  ? ((interval[0] + interval[1]) / 2) * 100
                                                  : 0
                                              return deltaPercent > 0 ? 'Won' : 'Lost'
                                          })()}
                                </LemonTag>
                            )}
                        </div>

                        <div className="flex justify-between items-center">
                            <span className="text-muted-alt font-semibold">Samples:</span>
                            <span className="font-semibold">{variantResult.number_of_samples}</span>
                        </div>

                        <div className="flex justify-between items-center">
                            <span className="text-muted-alt font-semibold">Sum:</span>
                            <span className="font-semibold">{variantResult.sum}</span>
                        </div>

                        {isBayesianResult(variantResult) ? (
                            <div className="flex justify-between items-center">
                                <span className="text-muted-alt font-semibold">Chance to win:</span>
                                <span className="font-semibold">{formatChanceToWin(variantResult.chance_to_win)}</span>
                            </div>
                        ) : (
                            <div className="flex justify-between items-center">
                                <span className="text-muted-alt font-semibold">P-value:</span>
                                <span className="font-semibold">{formatPValue(variantResult.p_value)}</span>
                            </div>
                        )}

                        <div className="flex justify-between items-center">
                            <span className="text-muted-alt font-semibold">Delta:</span>
                            <span className="font-semibold">
                                {variantResult.key === 'control' ? (
                                    <em className="text-muted-alt">Baseline</em>
                                ) : (
                                    (() => {
                                        const deltaPercent = interval ? ((lower + upper) / 2) * 100 : 0
                                        const isPositive = deltaPercent > 0
                                        return (
                                            <span className={isPositive ? 'text-success' : 'text-danger'}>
                                                {`${isPositive ? '+' : ''}${deltaPercent.toFixed(2)}%`}
                                            </span>
                                        )
                                    })()
                                )}
                            </span>
                        </div>

                        <div className="flex justify-between items-center">
                            <span className="text-muted-alt font-semibold">{intervalLabel}:</span>
                            <span className="font-semibold">{intervalPercent}</span>
                        </div>
                    </div>
                </div>
            )}
        </div>
    )
}
