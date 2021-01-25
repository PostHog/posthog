import {
    Command,
    commandPaletteLogic,
    CommandRegistrations,
    CommandResult,
    CommandFlow,
    RegExpCommandPairs,
    CommandResultDisplayable,
} from 'lib/components/CommandPalette/commandPaletteLogic'
import { commandPaletteLogicType } from './commandPaletteLogicType'
import { kea } from 'kea'
import { compareFilterLogic } from 'lib/components/CompareFilter/compareFilterLogic'
import { RiseOutlined } from '@ant-design/icons'
import { dateFilterLogic } from 'lib/components/DateFilter/dateFilterLogic'
import { dateMapping } from 'lib/utils'

const INSIGHT_COMMAND_SCOPE = 'insights'

export const insightCommandLogic = kea<
    commandPaletteLogicType<
        Command,
        CommandRegistrations,
        CommandResult,
        CommandFlow,
        RegExpCommandPairs,
        CommandResultDisplayable
    >
>({
    connect: [commandPaletteLogic, compareFilterLogic, dateFilterLogic],
    events: () => ({
        afterMount: () => {
            const funnelCommands: Command[] = [
                {
                    key: 'insight-graph',
                    resolver: [
                        {
                            icon: RiseOutlined,
                            display: 'Toggle "Compare Previous" on Graph',
                            executor: () => {
                                compareFilterLogic.actions.toggleCompare()
                            },
                        },
                        ...Object.entries(dateMapping).map(([key, value]) => ({
                            icon: RiseOutlined,
                            display: `Set Time Range to ${key}`,
                            executor: () => {
                                dateFilterLogic.actions.setDates(value[0], value[1])
                            },
                        })),
                    ],
                    scope: INSIGHT_COMMAND_SCOPE,
                },
            ]
            for (const command of funnelCommands) {
                commandPaletteLogic.actions.registerCommand(command)
            }
        },
        beforeUnmount: () => {
            commandPaletteLogic.actions.deregisterScope(INSIGHT_COMMAND_SCOPE)
        },
    }),
})
