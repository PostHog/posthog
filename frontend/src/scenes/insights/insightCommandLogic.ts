import { connect, events, kea, key, path, props } from 'kea'
import { Command, commandPaletteLogic } from 'lib/components/CommandPalette/commandPaletteLogic'
import { IconTrendingUp } from 'lib/lemon-ui/icons'
import { dateMapping } from 'lib/utils'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'

import { InsightLogicProps } from '~/types'

import type { insightCommandLogicType } from './insightCommandLogicType'
import { insightVizDataLogic } from './insightVizDataLogic'

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
