import React from 'react'

import { resolveVariableColor } from 'lib/charts/utils/color'

import { useChart } from '../core/chart-context'
import type { GoalLine } from '../core/types'

interface GoalLinesProps {
    goalLines: GoalLine[]
}

export function GoalLines({ goalLines }: GoalLinesProps): React.ReactElement {
    const { scales, dimensions } = useChart()

    return (
        <>
            {goalLines.map((goal, i) => {
                const y = scales.y(goal.value)
                if (!isFinite(y) || y < dimensions.plotTop || y > dimensions.plotTop + dimensions.plotHeight) {
                    return null
                }

                const color = resolveVariableColor(goal.borderColor) ?? 'rgba(0, 0, 0, 0.4)'

                return (
                    <React.Fragment key={i}>
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
