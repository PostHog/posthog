import { Command, commandPaletteLogic } from 'lib/components/CommandPalette/commandPaletteLogic'
import { kea } from 'kea'
import type { insightCommandLogicType } from './insightCommandLogicType'
import { compareFilterLogic } from 'lib/components/CompareFilter/compareFilterLogic'
import { RiseOutlined } from '@ant-design/icons'
import { dateMapping } from 'lib/utils'
import { InsightLogicProps } from '~/types'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { insightDateFilterLogic } from 'scenes/insights/InsightDateFilter/insightDateFilterLogic'

const INSIGHT_COMMAND_SCOPE = 'insights'

export const insightCommandLogic = kea<insightCommandLogicType>({
    props: {} as InsightLogicProps,
    key: keyForInsightLogicProps('new'),
    path: (key) => ['scenes', 'insights', 'insightCommandLogic', key],

    connect: (props: InsightLogicProps) => [
        commandPaletteLogic,
        compareFilterLogic(props),
        insightDateFilterLogic(props),
    ],
    events: ({ props }) => ({
        afterMount: () => {
            const funnelCommands: Command[] = [
                {
                    key: 'insight-graph',
                    resolver: [
                        {
                            icon: RiseOutlined,
                            display: 'Toggle "Compare Previous" on Graph',
                            executor: () => {
                                compareFilterLogic(props).actions.toggleCompare()
                            },
                        },
                        ...Object.entries(dateMapping).map(([key, { values }]) => ({
                            icon: RiseOutlined,
                            display: `Set Time Range to ${key}`,
                            executor: () => {
                                insightDateFilterLogic(props).actions.setDates(values[0], values[1])
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
