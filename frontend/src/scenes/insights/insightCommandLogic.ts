import { Command, commandPaletteLogic } from 'lib/components/CommandPalette/commandPaletteLogic'
import { kea, props, key, path, connect, events } from 'kea'
import type { insightCommandLogicType } from './insightCommandLogicType'
import { dateMapping } from 'lib/utils'
import { InsightLogicProps } from '~/types'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { insightVizDataLogic } from './insightVizDataLogic'
import { IconTrendingUp } from 'lib/lemon-ui/icons'

const INSIGHT_COMMAND_SCOPE = 'insights'

export const insightCommandLogic = kea<insightCommandLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps('new')),
    path((key) => ['scenes', 'insights', 'insightCommandLogic', key]),

    connect((props: InsightLogicProps) => [commandPaletteLogic, insightVizDataLogic(props)]),
    events(({ props }) => ({
        afterMount: () => {
            const funnelCommands: Command[] = [
                {
                    key: 'insight-graph',
                    resolver: [
                        {
                            icon: IconTrendingUp,
                            display: 'Toggle "Compare Previous" on Graph',
                            executor: () => {
                                const compare = insightVizDataLogic(props).values.compare
                                insightVizDataLogic(props).actions.updateInsightFilter({ compare: !compare })
                            },
                        },
                        ...dateMapping.map(({ key, values }) => ({
                            icon: IconTrendingUp,
                            display: `Set Time Range to ${key}`,
                            executor: () => {
                                insightVizDataLogic(props).actions.updateDateRange({
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
    })),
])
