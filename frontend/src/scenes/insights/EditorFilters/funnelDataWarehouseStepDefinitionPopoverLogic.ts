import { actions, connect, kea, key, path, props, reducers } from 'kea'

import { definitionPopoverLogic } from 'lib/components/DefinitionPopover/definitionPopoverLogic'
import { taxonomicFilterLogic } from 'lib/components/TaxonomicFilter/taxonomicFilterLogic'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'

import { InsightLogicProps } from '~/types'

export type FunnelFieldKey = 'id_field' | 'timestamp_field' | 'distinct_id_field'

export interface FunnelDataWarehouseStepDefinitionPopoverLogicProps {
    tableName: string
    taxonomicFilterLogicKey: string
    insightProps: InsightLogicProps
}

export const funnelDataWarehouseStepDefinitionPopoverLogic = kea([
    props({} as FunnelDataWarehouseStepDefinitionPopoverLogicProps),
    key((props) => props.tableName),
    path((key) => ['scenes', 'insights', 'EditorFilters', 'funnelDataWarehouseStepDefinitionPopoverLogic', key]),
    connect((props) => ({
        values: [
            taxonomicFilterLogic,
            ['dataWarehousePopoverFields'],
            definitionPopoverLogic,
            ['localDefinition'],
            funnelDataLogic(props.insightProps),
            ['querySource'],
        ],
        actions: [taxonomicFilterLogic, ['selectItem'], definitionPopoverLogic, ['setLocalDefinition']],
    })),
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
