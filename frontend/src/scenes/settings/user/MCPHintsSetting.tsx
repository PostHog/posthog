import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { userLogic } from 'scenes/userLogic'

export function MCPHintsSetting(): JSX.Element {
    const { user, userLoading } = useValues(userLogic)
    const { updateUser } = useActions(userLogic)

    return (
        <LemonSwitch
            onChange={(checked) => {
                updateUser({ hide_mcp_hints: !checked })
            }}
            checked={!(user?.hide_mcp_hints ?? false)}
            loading={userLoading}
            label="Show MCP hints after I take actions"
            bordered
        />
    )
}
