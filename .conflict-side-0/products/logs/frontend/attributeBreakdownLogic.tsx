import { connect, kea, key, path, props, selectors } from 'kea'

import type { attributeBreakdownLogicType } from './attributeBreakdownLogicType'
import { logsLogic } from './logsLogic'

export interface AttributeBreakdownLogicProps {
    attribute: string
}

export const attributeBreakdownLogic = kea<attributeBreakdownLogicType>([
    props({} as AttributeBreakdownLogicProps),
    key((props) => props.attribute),
    path((key) => ['products', 'logs', 'frontend', 'logsAttributeBreakdownsLogic', key]),

    connect(() => ({
        values: [logsLogic, ['logs']],
    })),

    selectors(({ props }) => ({
        logCount: [(s) => [s.logs], (logs): number => logs.length],
        attributeValues: [
            (s) => [s.logs],
            (logs): string[] =>
                logs.filter((l) => props.attribute in l.attributes).map((l) => l.attributes[props.attribute]),
        ],
        breakdowns: [
            (s) => [s.attributeValues],
            (attributeValues: string[]) =>
                attributeValues.reduce(
                    (acc, value) => {
                        acc[value] = (acc[value] || 0) + 1
                        return acc
                    },
                    {} as {
                        [key: string]: number
                    }
                ),
        ],
    })),
])
