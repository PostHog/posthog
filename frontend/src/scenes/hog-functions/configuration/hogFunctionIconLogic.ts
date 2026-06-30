import { actions, kea, key, path, props, reducers } from 'kea'

import type { hogFunctionIconLogicType } from './hogFunctionIconLogicType'

export interface HogFunctionIconLogicProps {
    logicKey: string
    src?: string
    onChange?: (src: string) => void
}

export const hogFunctionIconLogic = kea<hogFunctionIconLogicType>([
    props({} as HogFunctionIconLogicProps),
    key((props) => props.logicKey ?? 'default'),
    path((key) => ['scenes', 'pipeline', 'hogfunctions', 'hogFunctionIconLogic', key]),

    actions({
        setShowPopover: (show: boolean) => ({ show }),
    }),

    reducers({
        showPopover: [
            false,
            {
                setShowPopover: (_, { show }) => show,
            },
        ],
    }),
])
