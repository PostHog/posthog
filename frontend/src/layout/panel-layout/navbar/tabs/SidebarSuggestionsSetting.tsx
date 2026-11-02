import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { LemonSwitch } from '@posthog/lemon-ui'

import { userLogic } from 'scenes/userLogic'

export function SidebarSuggestionsSetting(): JSX.Element {
    const { user, userLoading } = useValues(userLogic)
    const { updateUser } = useActions(userLogic)

    return (
        <section className="flex flex-col gap-2">
            <LemonSwitch
                checked={user?.allow_sidebar_suggestions ?? false}
                loading={userLoading}
                onChange={(checked) => {
                    posthog.capture('sidebar suggestions toggled', { enabled: checked })
                    updateUser({ allow_sidebar_suggestions: checked })
                }}
                label="Suggest products as I use PostHog"
                bordered
                fullWidth
                data-attr="customize-sidebar-suggestions-toggle"
            />
            <p className="text-xs text-secondary mb-0">
                When you start using a product, we star it in your sidebar. We also show suggestions for related
                products.
            </p>
        </section>
    )
}
