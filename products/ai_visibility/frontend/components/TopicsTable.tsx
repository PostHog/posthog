import clsx from 'clsx'
import { useState } from 'react'

import { IconChevronRight, IconDownload, IconInfo } from '@posthog/icons'
import { LemonButton, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { Prompt, Topic } from '../types'
import { VisibilityBar } from './VisibilityBar'

function exportTopicsToCsv(topics: Topic[], brandName: string): void {
    const headers = [
        'Topic',
        'Prompt',
        'You Mentioned',
        'Competitors Mentioned',
        'Response',
        'Visibility %',
        'Relevancy %',
        'Avg Rank',
        'Citations',
    ]
    const rows: (string | number)[][] = []

    for (const topic of topics) {
        for (const prompt of topic.prompts) {
            rows.push([
                topic.name,
                prompt.text,
                prompt.you_mentioned ? 'Yes' : 'No',
                prompt.competitors_mentioned.join('; '),
                prompt.response || '',
                topic.visibility,
                topic.relevancy,
                topic.avgRank > 0 ? topic.avgRank.toFixed(1) : '',
                topic.citations,
            ])
        }
    }

    const escapeCsv = (cell: string | number): string => {
        const str = String(cell)
        return str.includes(',') || str.includes('"') || str.includes('\n') ? `"${str.replace(/"/g, '""')}"` : str
    }

    const csvContent = [headers, ...rows].map((row) => row.map(escapeCsv).join(',')).join('\n')

    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `${brandName.toLowerCase()}-ai-visibility-prompts.csv`
    link.click()
    URL.revokeObjectURL(url)
}

function PromptResponseExpander({ prompt }: { prompt: Prompt }): JSX.Element | null {
    const [isExpanded, setIsExpanded] = useState(false)

    if (!prompt.response) {
        return null
    }

    return (
        <div className="ml-6 mt-2">
            <button
                type="button"
                onClick={(e) => {
                    e.stopPropagation()
                    setIsExpanded(!isExpanded)
                }}
                className={clsx(
                    'flex items-center gap-1.5 text-xs px-2 py-1 rounded transition-colors',
                    isExpanded ? 'bg-bg-300 text-default' : 'text-muted hover:text-default hover:bg-bg-300'
                )}
            >
                <IconChevronRight className={clsx('w-3 h-3 transition-transform', isExpanded && 'rotate-90')} />
                <span>{isExpanded ? 'Hide' : 'View'} response</span>
            </button>
            {isExpanded && (
                <div className="mt-2 ml-1 p-3 bg-bg-300 rounded-lg border border-border">
                    <p className="text-xs font-semibold text-muted uppercase tracking-wide mb-2">Response</p>
                    <p className="text-sm text-default whitespace-pre-wrap leading-relaxed">{prompt.response}</p>
                </div>
            )}
        </div>
    )
}

export function TopicsTable({
    topics,
    brandName,
    brandDomain,
}: {
    topics: Topic[]
    brandName: string
    brandDomain: string
}): JSX.Element {
    const [expandedTopics, setExpandedTopics] = useState<Set<string>>(new Set())

    const toggleTopic = (name: string): void => {
        const newExpanded = new Set(expandedTopics)
        if (newExpanded.has(name)) {
            newExpanded.delete(name)
        } else {
            newExpanded.add(name)
        }
        setExpandedTopics(newExpanded)
    }

    return (
        <div className="border rounded-lg bg-bg-light">
            <div className="p-4 border-b flex items-center justify-between">
                <h3 className="text-sm font-semibold flex items-center gap-1">
                    Topics
                    <Tooltip title="All topics where your brand or competitors are mentioned. Expand a row to see the individual prompts and which brands were mentioned in each.">
                        <IconInfo className="w-4 h-4 text-muted" />
                    </Tooltip>
                </h3>
                <LemonButton
                    size="xsmall"
                    type="secondary"
                    icon={<IconDownload />}
                    onClick={() => exportTopicsToCsv(topics, brandName)}
                >
                    Export CSV
                </LemonButton>
            </div>
            <table className="w-full">
                <thead>
                    <tr className="border-b text-left text-xs text-muted uppercase">
                        <th className="p-3">Topic</th>
                        <th className="p-3 text-right">
                            <Tooltip title="% of prompts in this topic where your brand was mentioned">
                                <span className="cursor-help border-b border-dashed border-current">Visibility</span>
                            </Tooltip>
                        </th>
                        <th className="p-3 text-right">
                            <Tooltip title="% of prompts where AI recommended any brand — higher means the topic is more competitive">
                                <span className="cursor-help border-b border-dashed border-current">Relevancy</span>
                            </Tooltip>
                        </th>
                        <th className="p-3 text-right">
                            <Tooltip title="Your position among competitors based on mention frequency. #1 = most mentioned">
                                <span className="cursor-help border-b border-dashed border-current">Avg rank</span>
                            </Tooltip>
                        </th>
                        <th className="p-3 text-right">
                            <Tooltip title="Times AI cited sources when mentioning your brand">
                                <span className="cursor-help border-b border-dashed border-current">Citations</span>
                            </Tooltip>
                        </th>
                    </tr>
                </thead>
                <tbody>
                    {topics.map((topic) => (
                        <>
                            <tr
                                key={topic.name}
                                className="border-b hover:bg-bg-300 cursor-pointer"
                                onClick={() => toggleTopic(topic.name)}
                            >
                                <td className="p-3">
                                    <div className="flex items-center gap-2">
                                        <IconChevronRight
                                            className={clsx(
                                                'w-4 h-4 transition-transform',
                                                expandedTopics.has(topic.name) && 'rotate-90'
                                            )}
                                        />
                                        <div>
                                            <p className="font-medium">{topic.name}</p>
                                            <p className="text-xs text-muted">{topic.promptCount} prompts</p>
                                        </div>
                                    </div>
                                </td>
                                <td className="p-3">
                                    <div className="flex justify-end">
                                        <div className="flex items-center gap-2">
                                            {topic.topCompetitors.slice(0, 4).map((c) => (
                                                <Tooltip key={c.name} title={c.name}>
                                                    <div className="w-5 h-5 rounded-full bg-border overflow-hidden flex items-center justify-center text-[10px]">
                                                        {c.icon ? (
                                                            <img
                                                                src={c.icon}
                                                                alt={c.name}
                                                                className="w-full h-full object-contain"
                                                            />
                                                        ) : (
                                                            c.name.charAt(0)
                                                        )}
                                                    </div>
                                                </Tooltip>
                                            ))}
                                            <VisibilityBar value={topic.visibility} />
                                        </div>
                                    </div>
                                </td>
                                <td className="p-3 text-right">{topic.relevancy}%</td>
                                <td className="p-3 text-right">
                                    {topic.avgRank > 0 ? `#${topic.avgRank.toFixed(1)}` : '-'}
                                </td>
                                <td className="p-3 text-right">{topic.citations}</td>
                            </tr>
                            {expandedTopics.has(topic.name) && (
                                <tr key={`${topic.name}-expanded`}>
                                    <td colSpan={5} className="bg-bg-300 p-4">
                                        <div className="space-y-2">
                                            {topic.prompts.map((prompt) => {
                                                const competitors = prompt.competitors?.length
                                                    ? prompt.competitors
                                                    : prompt.competitors_mentioned.map((name) => ({
                                                          name,
                                                          logo_url: undefined,
                                                      }))
                                                return (
                                                    <div key={prompt.id} className="p-2 bg-bg-light rounded">
                                                        <div className="flex items-center justify-between">
                                                            <span className="text-sm">{prompt.text}</span>
                                                            <div className="flex items-center gap-2">
                                                                {prompt.you_mentioned && (
                                                                    <LemonTag type="highlight" size="small">
                                                                        <span className="flex items-center gap-1">
                                                                            <img
                                                                                src={`https://www.google.com/s2/favicons?domain=${brandDomain}&sz=32`}
                                                                                alt={brandName}
                                                                                className="w-4 h-4 rounded-full"
                                                                            />
                                                                            <span>{brandName}</span>
                                                                        </span>
                                                                    </LemonTag>
                                                                )}
                                                                {competitors.map((comp) => (
                                                                    <LemonTag key={comp.name} type="muted" size="small">
                                                                        <span className="flex items-center gap-1">
                                                                            {comp.logo_url ? (
                                                                                <img
                                                                                    src={comp.logo_url}
                                                                                    alt={comp.name}
                                                                                    className="w-4 h-4 rounded-full"
                                                                                />
                                                                            ) : (
                                                                                <span className="w-4 h-4 rounded-full bg-border flex items-center justify-center text-[10px]">
                                                                                    {comp.name.charAt(0)}
                                                                                </span>
                                                                            )}
                                                                            <span>{comp.name}</span>
                                                                        </span>
                                                                    </LemonTag>
                                                                ))}
                                                            </div>
                                                        </div>
                                                        <PromptResponseExpander prompt={prompt} />
                                                    </div>
                                                )
                                            })}
                                        </div>
                                    </td>
                                </tr>
                            )}
                        </>
                    ))}
                </tbody>
            </table>
        </div>
    )
}
