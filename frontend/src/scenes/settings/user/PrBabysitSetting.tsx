import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { userLogic } from 'scenes/userLogic'

export function PrBabysitSetting(): JSX.Element {
    const { user, userLoading } = useValues(userLogic)
    const { updateUser } = useActions(userLogic)

    return (
        <LemonSwitch
            onChange={(checked) => {
                updateUser({ pr_babysit_default: checked })
            }}
            checked={user?.pr_babysit_default ?? true}
            loading={userLoading}
            label="Babysit PRs by default"
            bordered
        />
    )
}
