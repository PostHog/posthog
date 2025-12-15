import { IconInfo } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { Topic } from '../types'
import { VisibilityBar } from './VisibilityBar'

export function TopTopicsList({ topics, onViewAll }: { topics: Topic[]; onViewAll?: () => void }): JSX.Element {
    return (
        <div className="border rounded-lg p-4 bg-bg-light">
            <div className="flex items-center justify-between mb-4">
                <h3 className="text-sm font-semibold flex items-center gap-1">
                    Top topics by visibility
                    <Tooltip title="Topics where your brand appears most frequently in AI responses. Higher visibility means AI mentions you more often for that topic.">
                        <IconInfo className="w-4 h-4 text-muted" />
                    </Tooltip>
                </h3>
                {onViewAll && (
                    <button onClick={onViewAll} className="text-xs text-primary hover:underline cursor-pointer">
                        View all
                    </button>
                )}
            </div>
            <div className="space-y-3">
                {topics.slice(0, 5).map((topic) => (
                    <div key={topic.name} className="flex items-center justify-between">
                        <div>
                            <p className="text-sm font-medium">{topic.name}</p>
                            <p className="text-xs text-muted">
                                {topic.promptCount} mentions in {topic.prompts.length} responses
                            </p>
                        </div>
                        <VisibilityBar value={topic.visibility} />
                    </div>
                ))}
            </div>
        </div>
    )
}
