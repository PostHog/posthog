import { LemonTag } from '@posthog/lemon-ui'

import type { AlertRouteMatcherApi } from '../generated/api.schemas'

export function RouteMatcherTags({ matchers }: { matchers: AlertRouteMatcherApi[] }): JSX.Element {
    if (matchers.length === 0) {
        return <LemonTag type="warning">All alerts</LemonTag>
    }
    return (
        <div className="flex flex-wrap gap-1" translate="no">
            {matchers.map((matcher) => (
                <LemonTag key={matcher.label} className="font-mono">
                    {`${matcher.label} = ${matcher.value}`}
                </LemonTag>
            ))}
        </div>
    )
}
