import { kea } from 'kea'
import {
    Command,
    commandPaletteLogic,
    CommandRegistrations,
    CommandResultTemplate,
} from 'lib/components/CommandPalette/commandPaletteLogic'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { commandPaletteLogicType } from 'types/lib/components/CommandPalette/commandPaletteLogicType'
import { FunnelPlotOutlined } from '@ant-design/icons'

const FUNNEL_COMMAND_SCOPE = 'funnels'

export const funnelCommandLogic = kea<commandPaletteLogicType<Command, CommandRegistrations>>({
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
            commandPaletteLogic.actions.deregisterAllWithMatch(FUNNEL_COMMAND_SCOPE)
        },
    }),
})
