import { kea } from 'kea'
import {
    Command,
    commandLogic,
    CommandRegistrations,
    CommandResultTemplate,
} from 'lib/components/CommandPalette/commandLogic'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { commandLogicType } from 'types/lib/components/CommandPalette/commandLogicType'
import { FunnelPlotOutlined } from '@ant-design/icons'

const FUNNEL_COMMAND_SCOPE = 'funnel-command'

export const funnelCommandLogic = kea<commandLogicType<Command, CommandRegistrations>>({
    events: () => ({
        afterMount: () => {
            const results: CommandResultTemplate[] = [
                {
                    key: 'funnel-clear',
                    icon: FunnelPlotOutlined,
                    display: 'Clear Funnel',
                    executor: () => {
                        funnelLogic.actions.clearFunnel()
                    },
                },
            ]

            const funnelCommands: Command[] = [
                {
                    key: FUNNEL_COMMAND_SCOPE,
                    prefixes: [],
                    resolver: results,
                    scope: FUNNEL_COMMAND_SCOPE,
                },
            ]
            for (const command of funnelCommands) {
                commandLogic.actions.registerCommand(command)
            }
        },
        beforeUnmount: () => {
            commandLogic.actions.deregisterCommand(FUNNEL_COMMAND_SCOPE)
        },
    }),
})
