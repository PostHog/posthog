import React from 'react'
import { useActions, useValues } from 'kea'
import { heatmapLogic } from '~/toolbar/shared/heatmapLogic'

export function HeatmapStats() {
    const { countedElements, eventCount } = useValues(heatmapLogic)
    const { highlightElement } = useActions(heatmapLogic)

    return (
        <div className="toolbar-block">
            Found: {countedElements.length} elements with {eventCount} clicks!
            {countedElements.map(({ element, count, actionStep }, index) => (
                <div
                    key={index}
                    onMouseEnter={() => highlightElement(element, true)}
                    onMouseLeave={() => highlightElement(null)}
                    style={{ cursor: 'pointer' }}
                >
                    {index + 1}. {actionStep.text} - {count} clicks
                </div>
            ))}
        </div>
    )
}
