import { actions, kea, path, reducers } from 'kea'

import type { agentSetupModalLogicType } from './agentSetupModalLogicType'

/** Setup widgets whose management UI opens in a modal. GitHub and MCP servers link out instead. */
export type AgentSetupModalKey = 'signal-sources' | 'scout-troop' | 'slack'

/** Tracks which agent-setup widget's modal is open (one at a time), driven from the widget strip. */
export const agentSetupModalLogic = kea<agentSetupModalLogicType>([
    path(['scenes', 'inbox', 'components', 'shell', 'agentSetupModalLogic']),

    actions({
        openSetupModal: (key: AgentSetupModalKey) => ({ key }),
        closeSetupModal: true,
    }),

    reducers({
        openModal: [
            null as AgentSetupModalKey | null,
            {
                openSetupModal: (_, { key }) => key,
                closeSetupModal: () => null,
            },
        ],
    }),
])
