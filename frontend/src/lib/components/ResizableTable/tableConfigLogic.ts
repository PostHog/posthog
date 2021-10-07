import { kea } from 'kea'
import { tableConfigLogicType } from './tableConfigLogicType'

export const tableConfigLogic = kea<tableConfigLogicType>({
    actions: {
        setModalVisible: (visible: boolean) => ({ visible }),
    },
    reducers: {
        modalVisible: [
            false,
            {
                setModalVisible: (_, { visible }) => visible,
            },
        ],
    },
})
