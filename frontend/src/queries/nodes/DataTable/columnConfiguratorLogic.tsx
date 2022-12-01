import { actions, kea, path, props, reducers } from 'kea'

import type { columnConfiguratorLogicType } from './columnConfiguratorLogicType'

export interface ColumnConfiguratorLogicProps {
    key: string
    columns: string[]
}

export const columnConfiguratorLogic = kea<columnConfiguratorLogicType>([
    props({} as ColumnConfiguratorLogicProps),
    path(['queries', 'nodes', 'DataTable', 'columnConfiguratorLogic']),
    actions({
        showModal: true,
        hideModal: true,
    }),
    reducers({
        modalVisible: [
            false,
            {
                showModal: () => true,
                hideModal: () => false,
                setSelectedColumns: () => false,
            },
        ],
    }),
])
