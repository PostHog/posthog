import { Command, commandPaletteLogic } from 'lib/components/CommandPalette/commandPaletteLogic'
import { kea } from 'kea'
import { insightCommandLogicType } from './insightCommandLogicType'
import { compareFilterLogic } from 'lib/components/CompareFilter/compareFilterLogic'
import { RiseOutlined } from '@ant-design/icons'
import { dateMapping } from 'lib/utils'
import { InsightLogicProps } from '~/types'
import { insightLogic } from 'scenes/insights/insightLogic'

const INSIGHT_COMMAND_SCOPE = 'insights'

export const insightCommandLogic = kea<insightCommandLogicType>({
    props: {} as InsightLogicProps,
    path: ['scenes', 'insights', 'insightCommandLogic'],
    connect: (props: InsightLogicProps) => ({
        actions: [insightLogic(props), ['setFilters']],
        logic: [commandPaletteLogic, compareFilterLogic],
    }),
    events: ({ actions }) => ({
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
                        ...Object.entries(dateMapping)
                            .filter(([, { inactive }]) => !inactive)
                            .map(([key, { values }]) => ({
                                icon: RiseOutlined,
                                display: `Set Time Range to ${key}`,
                                executor: () => {
                                    actions.setFilters({
                                        date_from: values[0],
                                        date_to: values[1],
                                    })
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
