import { kea } from 'kea'
import {
    Command,
    commandPaletteLogic,
    CommandRegistrations,
    CommandResult,
    CommandResultTemplate,
    CommandFlow,
    RegExpCommandPairs,
} from 'lib/components/CommandPalette/commandPaletteLogic'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { commandPaletteLogicType } from 'types/lib/components/CommandPalette/commandPaletteLogicType'
import { FunnelPlotOutlined } from '@ant-design/icons'

const FUNNEL_COMMAND_SCOPE = 'funnels'

export const funnelCommandLogic = kea<
    commandPaletteLogicType<Command, CommandRegistrations, CommandResult, CommandFlow, RegExpCommandPairs>
>({
    connect: [commandPaletteLogic],
    events: () => ({
        afterMount: () => {
            const results: CommandResultTemplate[] = [
                {
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
                    resolver: results,
                    scope: FUNNEL_COMMAND_SCOPE,
                },
            ]
            for (const command of funnelCommands) {
                commandPaletteLogic.actions.registerCommand(command)
            }
        },
        beforeUnmount: () => {
            commandPaletteLogic.actions.deregisterScope(FUNNEL_COMMAND_SCOPE)
        },
    }),
})
