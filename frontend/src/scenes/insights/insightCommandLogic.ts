import {
    Command,
    commandLogic,
    CommandRegistrations,
    CommandResultTemplate,
} from 'lib/components/CommandPalette/commandLogic'
import { commandLogicType } from 'types/lib/components/CommandPalette/commandLogicType'
import { kea } from 'kea'
import { compareFilterLogic } from 'lib/components/CompareFilter/compareFilterLogic'
import { RiseOutlined } from '@ant-design/icons'
import { dateFilterLogic } from 'lib/components/DateFilter/dateFilterLogic'
import { dateMapping } from 'lib/utils'

const INSIGHT_COMMAND_SCOPE = 'Insights'

export const insightCommandLogic = kea<commandLogicType<Command, CommandRegistrations>>({
    connect: [commandLogic, compareFilterLogic, dateFilterLogic],
    events: () => ({
        afterMount: () => {
            const results: CommandResultTemplate[] = [
                {
                    key: 'insight-compare',
                    icon: RiseOutlined,
                    display: 'Toggle compare',
                    executor: () => {
                        compareFilterLogic.actions.setCompare(!compareFilterLogic.values.compare)
                    },
                },
                ...Object.entries(dateMapping).map(([key, value]) => ({
                    key: `insight-${key}`,
                    icon: RiseOutlined,
                    display: `Set time range to ${key}`,
                    executor: () => {
                        dateFilterLogic.actions.setDates(value[0], value[1])
                    },
                })),
            ]

            const funnelCommands: Command[] = [
                {
                    key: 'insight-graph',
                    prefixes: [],
                    resolver: results,
                    scope: INSIGHT_COMMAND_SCOPE,
                },
            ]
            for (const command of funnelCommands) {
                commandLogic.actions.registerCommand(command)
            }
        },
        beforeUnmount: () => {
            commandLogic.actions.deregisterAllWithMatch(INSIGHT_COMMAND_SCOPE)
        },
    }),
})
