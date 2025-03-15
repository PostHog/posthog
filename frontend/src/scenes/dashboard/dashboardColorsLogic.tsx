import { actions, kea, key, path, props, reducers } from 'kea'
import { DataColorToken } from 'lib/colors'

import type { dashboardColorsLogicType } from './dashboardColorsLogicType'
import { DashboardLogicProps } from './dashboardLogic'

export const dashboardColorsLogic = kea<dashboardColorsLogicType>([
    path((key) => ['scenes', 'dashboard', 'dashboardColorsLogic', key]),
    props({} as DashboardLogicProps),
    key((props) => {
        if (props.id == null) {
            return ''
        }
        return props.id
    }),

    actions(() => ({
        setResultColorUsed: (...rest) => ({ ...rest }),
        setBreakdownColor: (breakdownValue: string, colorToken: DataColorToken) => ({ breakdownValue, colorToken }),
    })),

    reducers(() => ({
        breakdownColors: [
            {},
            {
                setBreakdownColor: (state, { breakdownValue, colorToken }) => {
                    return { ...state, [breakdownValue]: colorToken }
                },
            },
        ],
    })),
])
