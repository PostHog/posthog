import { actions, kea, key, path, props, reducers } from 'kea'

export type FunnelFieldKey = 'id_field' | 'timestamp_field' | 'distinct_id_field'

export interface FunnelDataWarehouseStepDefinitionPopoverLogicProps {
    tableName: string
}

export const funnelDataWarehouseStepDefinitionPopoverLogic = kea([
    props({} as FunnelDataWarehouseStepDefinitionPopoverLogicProps),
    key((props) => props.tableName),
    path((key) => ['scenes', 'insights', 'EditorFilters', 'funnelDataWarehouseStepDefinitionPopoverLogic', key]),
    actions(() => ({
        setActiveFieldKey: (activeFieldKey: FunnelFieldKey) => ({ activeFieldKey }),
    })),
    reducers({
        activeFieldKey: [
            'id_field' as FunnelFieldKey,
            {
                setActiveFieldKey: (_, { activeFieldKey }) => activeFieldKey,
            },
        ],
    }),
])
