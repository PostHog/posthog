import { Command, commandPaletteLogic } from 'lib/components/CommandPalette/commandPaletteLogic'
import { kea } from 'kea'
import { insightCommandLogicType } from './insightCommandLogicType'
import { compareFilterLogic } from 'lib/components/CompareFilter/compareFilterLogic'
import { RiseOutlined } from '@ant-design/icons'
import { insightDateFilterLogic } from 'scenes/insights/InsightDateFilter/insightDateFilterLogic'
import { dateMapping } from 'lib/utils'

const INSIGHT_COMMAND_SCOPE = 'insights'

export const insightCommandLogic = kea<insightCommandLogicType>({
    connect: [commandPaletteLogic, compareFilterLogic, insightDateFilterLogic],
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
                        ...Object.entries(dateMapping).map(([key, { values }]) => ({
                            icon: RiseOutlined,
                            display: `Set Time Range to ${key}`,
                            executor: () => {
                                insightDateFilterLogic.actions.setDates(values[0], values[1])
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
