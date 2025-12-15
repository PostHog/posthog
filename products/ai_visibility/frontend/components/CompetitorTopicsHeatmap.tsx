import clsx from 'clsx'
import { useState } from 'react'

import { IconInfo } from '@posthog/icons'
import { LemonSegmentedButton, Tooltip } from '@posthog/lemon-ui'

import { MatrixCell, Topic } from '../types'
import { TopicCompetitorBreakdownModal } from './TopicCompetitorBreakdownModal'

export function CompetitorTopicsHeatmap({
    matrix,
    topics,
    competitors,
    brandName,
    brandDomain,
    visibilityScore,
}: {
    matrix: MatrixCell[]
    topics: Topic[]
    competitors: { name: string; visibility: number; domain?: string }[]
    brandName: string
    brandDomain: string
    visibilityScore: number
}): JSX.Element {
    const [showRank, setShowRank] = useState(false)
    const [selectedTopic, setSelectedTopic] = useState<Topic | null>(null)
    const [selectedCompetitor, setSelectedCompetitor] = useState<string | null>(null)

    const handleCellClick = (topic: Topic, competitorName: string): void => {
        if (competitorName === brandName) {
            return
        }
        setSelectedTopic(topic)
        setSelectedCompetitor(competitorName)
    }

    const handleCloseModal = (): void => {
        setSelectedTopic(null)
        setSelectedCompetitor(null)
    }

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

    const allCompetitors = [{ name: brandName, visibility: visibilityScore, domain: brandDomain }, ...competitors]

    return (
        <div className="border rounded-lg bg-bg-light overflow-hidden">
            <div className="flex items-center justify-between p-4 border-b">
                <h3 className="text-sm font-semibold flex items-center gap-1">
                    Competitors vs topics matrix
                    <Tooltip title="Shows visibility percentage for each brand across different topics. Darker blue = higher visibility. Use this to identify which topics you dominate vs where competitors are winning.">
                        <IconInfo className="w-4 h-4 text-muted" />
                    </Tooltip>
                </h3>
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
                            {allCompetitors.map((comp) => {
                                const faviconDomain = comp.domain || comp.name
                                return (
                                    <th key={comp.name} className="p-3 text-center font-medium min-w-[80px]">
                                        <div className="flex flex-col items-center gap-1">
                                            <div className="w-6 h-6 rounded-full bg-border flex items-center justify-center text-xs">
                                                <img
                                                    src={`https://www.google.com/s2/favicons?domain=${faviconDomain}&sz=32`}
                                                    alt=""
                                                    className="w-5 h-5 rounded"
                                                />
                                            </div>
                                            <span className="text-xs truncate max-w-[70px]">{comp.name}</span>
                                        </div>
                                    </th>
                                )
                            })}
                        </tr>
                    </thead>
                    <tbody>
                        {topics.map((topic) => (
                            <tr key={topic.name} className="border-b">
                                <td className="p-3 font-medium">{topic.name}</td>
                                {allCompetitors.map((comp) => {
                                    const cellValue = getCell(topic.name, comp.name)?.visibility ?? 0
                                    const isClickable = comp.name !== brandName

                                    return (
                                        <td key={comp.name} className="p-1">
                                            <div
                                                className={clsx(
                                                    'p-2 text-center rounded text-xs font-medium',
                                                    getCellColor(cellValue),
                                                    isClickable && 'cursor-pointer hover:ring-2 hover:ring-primary'
                                                )}
                                                onClick={
                                                    isClickable ? () => handleCellClick(topic, comp.name) : undefined
                                                }
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
            <TopicCompetitorBreakdownModal
                isOpen={selectedTopic !== null && selectedCompetitor !== null}
                onClose={handleCloseModal}
                topic={selectedTopic}
                competitor={selectedCompetitor}
                brandName={brandName}
            />
        </div>
    )
}
