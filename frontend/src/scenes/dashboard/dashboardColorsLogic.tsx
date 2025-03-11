import { actions, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import type { dashboardColorsLogicType } from './dashboardColorsLogicType'
import { DashboardLogicProps } from './dashboardLogic'

export const dashboardColorsLogic = kea<dashboardColorsLogicType>([
    path((key) => ['scenes', 'dashboard', 'dashboardColorsLogic', key]),
    props({} as DashboardLogicProps),
    key((props) => {
        if (typeof props.id !== 'number') {
            throw Error('Must init dashboardLogic with a numeric ID key')
        }
        return props.id
    }),

    actions(() => ({
        setResultColorUsed: (...rest) => ({ ...rest }),
    })),

    reducers(() => ({
        resultCustomizations: [
            {
                '{"breakdown_value":"Baseline"}': {
                    assignmentBy: 'value',
                    color: 'preset-8',
                },
            },
            {
                setResultColorUsed: () => ({
                    '{"breakdown_value":"Baseline"}': {
                        assignmentBy: 'value',
                        color: 'preset-8',
                    },
                }),
            },
        ],
    })),
    listeners({
        setResultColorUsed: ({ key, colorToken, ...rest }, ...s) => {
            console.debug('key', key)
            console.debug('colorToken', colorToken)
            console.debug('rest', rest)
            console.debug('s', s)
        },
    }),
    // selectors(() => ({
    //     canAutoPreview: [(s) => [s.dashboard], (dashboard) => false],
    // })),
])
