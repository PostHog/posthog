import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { userLogic } from 'scenes/userLogic'

export function OptOutCapture(): JSX.Element {
    const { user, userLoading } = useValues(userLogic)
    const { updateUser } = useActions(userLogic)

    return (
        <div>
            <p>
                PostHog uses PostHog (unsurprisingly!) to capture information about how people are using the product. We
                believe that product analytics is crucial to making PostHog the most useful it can be, for everyone.
            </p>
            <p>
                We also understand there are many reasons why people don't want to or aren't allowed to send this usage
                data. If you would like to anonymize your personal usage data, just tick the box below.
            </p>
            <LemonSwitch
                label="Anonymize my data"
                data-attr="anonymize-data-collection"
                onChange={(checked) => updateUser({ anonymize_data: checked })}
                checked={user?.anonymize_data ?? false}
                disabled={userLoading}
                bordered
            />
        </div>
    )
}
