import clsx from 'clsx'
import { useState } from 'react'

import { IconCheck, IconChevronRight, IconInfo, IconX } from '@posthog/icons'
import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { Topic } from '../types'
import { CategoryTag } from './CategoryTag'
import { VisibilityBar } from './VisibilityBar'

export function TopicsTable({ topics }: { topics: Topic[] }): JSX.Element {
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
            <div className="p-4 border-b">
                <h3 className="text-sm font-semibold flex items-center gap-1">
                    Topics
                    <Tooltip title="All topics where your brand or competitors are mentioned. Expand a row to see the individual prompts and which brands were mentioned in each.">
                        <IconInfo className="w-4 h-4 text-muted" />
                    </Tooltip>
                </h3>
            </div>
            <table className="w-full">
                <thead>
                    <tr className="border-b text-left text-xs text-muted uppercase">
                        <th className="p-3">Topic</th>
                        <th className="p-3 text-right">Visibility</th>
                        <th className="p-3 text-right">Relevancy</th>
                        <th className="p-3 text-right">Avg rank</th>
                        <th className="p-3 text-right">Citations</th>
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
                                            {topic.prompts.map((prompt) => (
                                                <div
                                                    key={prompt.id}
                                                    className="flex items-center justify-between p-2 bg-bg-light rounded"
                                                >
                                                    <div className="flex items-center gap-2">
                                                        {prompt.you_mentioned ? (
                                                            <IconCheck className="w-4 h-4 text-success" />
                                                        ) : (
                                                            <IconX className="w-4 h-4 text-muted" />
                                                        )}
                                                        <span className="text-sm">{prompt.text}</span>
                                                    </div>
                                                    <div className="flex items-center gap-2">
                                                        <CategoryTag category={prompt.category} />
                                                        {(prompt.competitors?.length
                                                            ? prompt.competitors
                                                            : prompt.competitors_mentioned.map((name) => ({
                                                                  name,
                                                                  logo_url: undefined,
                                                              }))
                                                        ).map((comp) => (
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
                                            ))}
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
