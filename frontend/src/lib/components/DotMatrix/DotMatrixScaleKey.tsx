import { DotMatrixSymbol } from './DotMatrixSymbol'
import type { DotMatrixCountBin, DotMatrixLegendLabels } from './types'

interface DotMatrixScaleKeyProps {
    mode: 'dots' | 'count'
    sizeThresholds: number[]
    countScale?: DotMatrixCountBin[]
    labels?: DotMatrixLegendLabels
}

export function DotMatrixScaleKey({ mode, sizeThresholds, countScale, labels }: DotMatrixScaleKeyProps): JSX.Element {
    return (
        <>
            {mode === 'dots' ? (
                <div className="DotMatrix__size-key">
                    <span>{labels?.valueLabel ?? 'Value'}</span>
                    {sizeThresholds.slice(0, 3).map((threshold) => (
                        <span className="DotMatrix__key-item" key={threshold}>
                            <svg width="17" height="17" viewBox="0 0 17 17" aria-hidden="true">
                                <DotMatrixSymbol value={threshold} thresholds={sizeThresholds} color="currentColor" />
                            </svg>
                            <b>{`${threshold}+`}</b>
                        </span>
                    ))}
                </div>
            ) : (
                !!countScale && (
                    <div className="DotMatrix__count-key">
                        <span>{labels?.countLabel ?? 'Count'}</span>
                        {countScale.map((bin, index) => (
                            <span className="DotMatrix__key-item" key={bin.min}>
                                <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">
                                    <rect width="14" height="14" rx="3" fill={bin.color} />
                                </svg>
                                <span>
                                    {bin.label ??
                                        (countScale[index + 1]
                                            ? `${bin.min}-${countScale[index + 1].min - 1}`
                                            : `${bin.min}+`)}
                                </span>
                            </span>
                        ))}
                    </div>
                )
            )}
        </>
    )
}
