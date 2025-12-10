import clsx from 'clsx'
import { useState } from 'react'

import { LemonSegmentedButton } from '@posthog/lemon-ui'

import { MatrixCell, Topic } from '../types'

export function CompetitorTopicsHeatmap({
    matrix,
    topics,
    competitors,
    brandName,
    visibilityScore,
}: {
    matrix: MatrixCell[]
    topics: Topic[]
    competitors: { name: string; visibility: number }[]
    brandName: string
    visibilityScore: number
}): JSX.Element {
    const [showRank, setShowRank] = useState(false)

    const getCell = (topicName: string, competitorName: string): MatrixCell | undefined => {
        return matrix.find((c) => c.topic === topicName && c.competitor === competitorName)
    }

    const getCellColor = (visibility: number): string => {
        if (visibility >= 70) {
            return 'bg-[#1e40af] text-white'
        }
        if (visibility >= 50) {
            return 'bg-[#3b82f6] text-white'
        }
        if (visibility >= 30) {
            return 'bg-[#93c5fd] text-gray-900'
        }
        if (visibility >= 10) {
            return 'bg-[#dbeafe] text-gray-700'
        }
        return 'bg-[#f1f5f9] text-gray-500'
    }

    const allCompetitors = [{ name: brandName, visibility: visibilityScore }, ...competitors]

    return (
        <div className="border rounded-lg bg-bg-light overflow-hidden">
            <div className="flex items-center justify-between p-4 border-b">
                <h3 className="text-sm font-semibold">Competitors vs topics matrix</h3>
                <LemonSegmentedButton
                    size="small"
                    value={showRank ? 'rank' : 'visibility'}
                    onChange={(val) => setShowRank(val === 'rank')}
                    options={[
                        { value: 'visibility', label: 'Visibility percentage' },
                        { value: 'rank', label: 'Average rank' },
                    ]}
                />
            </div>
            <div className="overflow-x-auto">
                <table className="w-full text-sm">
                    <thead>
                        <tr className="border-b">
                            <th className="p-3 text-left font-medium">Topic</th>
                            {allCompetitors.map((comp) => (
                                <th key={comp.name} className="p-3 text-center font-medium min-w-[80px]">
                                    <div className="flex flex-col items-center gap-1">
                                        <div className="w-6 h-6 rounded-full bg-border flex items-center justify-center text-xs">
                                            {comp.name.charAt(0)}
                                        </div>
                                        <span className="text-xs truncate max-w-[70px]">{comp.name}</span>
                                    </div>
                                </th>
                            ))}
                        </tr>
                    </thead>
                    <tbody>
                        {topics.map((topic) => (
                            <tr key={topic.name} className="border-b">
                                <td className="p-3 font-medium">{topic.name}</td>
                                {allCompetitors.map((comp) => {
                                    const cellValue = getCell(topic.name, comp.name)?.visibility ?? 0

                                    return (
                                        <td key={comp.name} className="p-1">
                                            <div
                                                className={clsx(
                                                    'p-2 text-center rounded text-xs font-medium',
                                                    getCellColor(cellValue)
                                                )}
                                            >
                                                {showRank
                                                    ? (() => {
                                                          const cell = getCell(topic.name, comp.name)
                                                          const rank = cell?.avgRank
                                                          return rank && rank > 0 ? `#${rank}` : '-'
                                                      })()
                                                    : `${cellValue}%`}
                                            </div>
                                        </td>
                                    )
                                })}
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    )
}
