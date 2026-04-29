import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconArrowLeft } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { urls } from 'scenes/urls'

import { botDetailLogic } from './botDetailLogic'
import { Tiles } from './WebAnalyticsDashboard'
import { webAnalyticsLogic } from './webAnalyticsLogic'

export function BotDetail(): JSX.Element {
    const { botDetailName } = useValues(webAnalyticsLogic)
    const { setBotDetailName } = useActions(webAnalyticsLogic)
    const { tiles } = useValues(botDetailLogic)

    if (!botDetailName) {
        return <div />
    }

    return (
        <div className="space-y-2 mt-2 h-full min-h-0">
            <div className="flex items-center gap-2">
                <LemonButton
                    type="tertiary"
                    size="small"
                    icon={<IconArrowLeft />}
                    onClick={() => {
                        setBotDetailName(null)
                        router.actions.push(urls.webAnalyticsBotAnalytics())
                    }}
                >
                    All crawlers
                </LemonButton>
                <h2 className="text-lg font-semibold mb-0">{botDetailName}</h2>
            </div>
            <Tiles tiles={tiles} compact={true} />
        </div>
    )
}
