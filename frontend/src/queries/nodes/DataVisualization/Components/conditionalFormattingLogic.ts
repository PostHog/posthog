import { actions, connect, kea, key, listeners, path, props } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'

import { dataVisualizationLogic } from '../dataVisualizationLogic'
import type { conditionalFormattingLogicType } from './conditionalFormattingLogicType'

export interface ConditionalFormattingLogicProps {
    key: string
}

export const conditionalFormattingLogic = kea<conditionalFormattingLogicType>([
    key((props) => props.key),
    path(['queries', 'nodes', 'DataVisualization', 'Components', 'conditionalFormattingLogic']),
    props({ key: '' } as ConditionalFormattingLogicProps),
    connect({
        values: [dataVisualizationLogic, ['query']],
        actions: [dataVisualizationLogic, ['setQuery']],
    }),
    actions({
        saveFormatting: true,
    }),
    loaders({
        hog: [
            null as null | any[],
            {
                compileHog: async ({ hog }) => {
                    const res = await api.hog.create(hog)
                    console.log(res)
                    return res.bytecode
                },
            },
        ],
    }),
    listeners(({ values, actions }) => ({
        saveFormatting: () => {
            if (!values.hog) {
                return
            }

            actions.setQuery({
                ...values.query,
                tableSettings: {
                    ...values.query?.tableSettings,
                    conditionalFormatting: [
                        {
                            columnName: 'test',
                            bytecode: values.hog,
                        },
                    ],
                },
            })
        },
    })),
])
