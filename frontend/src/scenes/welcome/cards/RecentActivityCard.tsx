import { useActions, useValues } from 'kea'

import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { Link } from 'lib/lemon-ui/Link'

import { welcomeDialogLogic } from '../welcomeDialogLogic'

const ACTIVITY_VERBS: Record<string, string> = {
    Insight: 'created an insight',
    Dashboard: 'shared a dashboard',
    Notebook: 'wrote a notebook',
    Experiment: 'launched an experiment',
    FeatureFlag: 'shipped a feature flag',
    Survey: 'launched a survey',
}

function activityDescription(type: string): string {
    const [scope] = type.split('.')
    return ACTIVITY_VERBS[scope] ?? 'made a change'
}

export function RecentActivityCard(): JSX.Element | null {
    const { recentActivity } = useValues(welcomeDialogLogic)
    const { trackCardClick } = useActions(welcomeDialogLogic)

    if (recentActivity.length === 0) {
        return null
    }

    return (
        <LemonCard hoverEffect={false} className="p-6">
            <h2 className="text-lg font-semibold mb-3">What your team has been doing</h2>
            <ul className="flex flex-col gap-2">
                {recentActivity.map((item, index) => {
                    const verb = activityDescription(item.type)
                    const content = (
                        <span>
                            <span className="font-medium">{item.actor_name}</span>
                            {` ${verb}: `}
                            <span className="font-medium">{item.entity_name}</span>
                        </span>
                    )
                    return (
                        <li key={`${item.type}-${index}`} className="text-sm">
                            {item.entity_url ? (
                                <Link to={item.entity_url} onClick={() => trackCardClick('activity', item.entity_url!)}>
                                    {content}
                                </Link>
                            ) : (
                                content
                            )}
                        </li>
                    )
                })}
            </ul>
        </LemonCard>
    )
}
