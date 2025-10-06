import { useActions, useValues } from 'kea'

import { IconEllipsis, IconSearch } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { urls } from 'scenes/urls'
import { webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'

export const WebAnalyticsMenu = (): JSX.Element => {
    const { shouldFilterTestAccounts } = useValues(webAnalyticsLogic)

    const { setShouldFilterTestAccounts } = useActions(webAnalyticsLogic)

    return (
        <LemonMenu
            items={[
                {
                    label: 'Session Attribution Explorer',
                    to: urls.sessionAttributionExplorer(),
                    icon: <IconSearch />,
                },
                {
                    label: () => (
                        <LemonSwitch
                            checked={shouldFilterTestAccounts}
                            onChange={() => {
                                setShouldFilterTestAccounts(!shouldFilterTestAccounts)
                            }}
                            fullWidth={true}
                            label="Filter test accounts"
                        />
                    ),
                },
            ].filter(Boolean)}
            closeOnClickInside={false}
        >
            <LemonButton icon={<IconEllipsis />} size="small" />
        </LemonMenu>
    )
}
