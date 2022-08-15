import { kea } from 'kea'
import { Command, commandPaletteLogic, CommandResultTemplate } from 'lib/components/CommandPalette/commandPaletteLogic'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { FunnelPlotOutlined } from '@ant-design/icons'

import type { funnelCommandLogicType } from './funnelCommandLogicType'

const FUNNEL_COMMAND_SCOPE = 'funnels'

export const funnelCommandLogic = kea<funnelCommandLogicType>({
    path: ['scenes', 'insights', 'InsightTabs', 'FunnelTab', 'funnelCommandLogic'],
    connect: [commandPaletteLogic],
    events: {
        afterMount: () => {
            const results: CommandResultTemplate[] = [
                {
                    icon: FunnelPlotOutlined,
                    display: 'Clear Funnel',
                    executor: () => {
                        funnelLogic.findMounted({ syncWithUrl: true })?.actions.clearFunnel()
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
    },
})
