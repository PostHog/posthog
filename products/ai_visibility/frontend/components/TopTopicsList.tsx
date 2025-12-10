import { Link } from 'lib/lemon-ui/Link'

import { Topic } from '../types'
import { VisibilityBar } from './VisibilityBar'

export function TopTopicsList({ topics }: { topics: Topic[] }): JSX.Element {
    return (
        <div className="border rounded-lg p-4 bg-bg-light">
            <div className="flex items-center justify-between mb-4">
                <h3 className="text-sm font-semibold">Top topics by visibility</h3>
                <Link to="#" className="text-xs text-primary">
                    View all
                </Link>
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
