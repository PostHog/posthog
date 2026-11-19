import { useActions } from 'kea'
import { useMemo } from 'react'

import { useSceneAgentPanel } from 'scenes/max/useSceneAgentPanel'

import { useToolStreamListener } from 'products/posthog_ai/frontend/api/logics'

import type { AccountApi } from '../../generated/api.schemas'
import {
    ACCOUNT_AGENT_WRITE_TOOLS,
    createAccountAgentContextItems,
    parseAccountAgentWrite,
} from './accountAgentContext'
import { customerAnalyticsAccountSceneLogic } from './customerAnalyticsAccountSceneLogic'

export function AccountAgentIntegration({ account }: { account: AccountApi }): null {
    const { refreshAfterAgentWrite } = useActions(customerAnalyticsAccountSceneLogic)

    const contextItems = useMemo(
        () => createAccountAgentContextItems({ id: account.id, name: account.name }),
        [account.id, account.name]
    )

    useSceneAgentPanel({ sceneKey: 'customer-analytics-account', contextItems, autoOpen: false })

    // A plain listener, not `useMcpToolApplyBack`: the reload is idempotent and targets the account
    // by ID, so a change made by a background run must refresh the page too.
    useToolStreamListener({
        tools: ACCOUNT_AGENT_WRITE_TOOLS,
        onEvent: (event) => {
            const write = parseAccountAgentWrite(event)
            if (write) {
                refreshAfterAgentWrite(write)
            }
        },
    })

    return null
}
