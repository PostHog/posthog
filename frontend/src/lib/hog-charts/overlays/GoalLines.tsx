import React from 'react'

import { resolveVariableColor } from 'lib/charts/utils/color'

import type { ChartDimensions, GoalLine } from '../core/types'

interface GoalLinesProps {
    goalLines: GoalLine[]
    yScale: (value: number) => number
    dimensions: ChartDimensions
}

export function GoalLines({ goalLines, yScale, dimensions }: GoalLinesProps): React.ReactElement {
    return (
        <>
            {goalLines.map((goal, i) => {
                const y = yScale(goal.value)
                if (!isFinite(y) || y < dimensions.plotTop || y > dimensions.plotTop + dimensions.plotHeight) {
                    return null
                }

                const color = resolveVariableColor(goal.borderColor) ?? 'rgba(0, 0, 0, 0.4)'

                return (
                    <React.Fragment key={i}>
                        {/* Dashed line */}
                        <div
                            style={{
                                position: 'absolute',
                                left: dimensions.plotLeft,
                                top: y,
                                width: dimensions.plotWidth,
                                height: 0,
                                borderTop: `2px dashed ${color}`,
                                pointerEvents: 'none',
                            }}
                        />
                        {/* Label */}
                        {goal.label && (
                            <div
                                style={{
                                    position: 'absolute',
                                    top: y - 18,
                                    ...(goal.position === 'end'
                                        ? { right: dimensions.width - dimensions.plotLeft - dimensions.plotWidth }
                                        : { left: dimensions.plotLeft + 4 }),
                                    fontSize: 11,
                                    color,
                                    pointerEvents: 'none',
                                    whiteSpace: 'nowrap',
                                    fontWeight: 500,
                                }}
                            >
                                {goal.label}
                            </div>
                        )}
                    </React.Fragment>
                )
            })}
        </>
    )
}
