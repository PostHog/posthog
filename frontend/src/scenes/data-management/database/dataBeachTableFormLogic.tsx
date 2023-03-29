import { lemonToast } from '@posthog/lemon-ui'
import { kea, key, props, path, selectors } from 'kea'
import { forms } from 'kea-forms'
import api from 'lib/api'
import { DataBeachTableType, DataBeachFieldType } from '~/types'

import type { dataBeachTableFormLogicType } from './dataBeachTableFormLogicType'

export interface DataBeachTableFormLogicProps {
    dataBeachTable: DataBeachTableType | null
    onSave: (dataBeachTable: DataBeachTableType) => void
    onCancel?: () => void
}

export const EMPTY_DATA_BEACH_FIELD: DataBeachFieldType = { name: '', type: 'String' }
export const EMPTY_DATA_BEACH_TABLE: DataBeachTableType = {
    name: '',
    engine: 'appendable',
    fields: [EMPTY_DATA_BEACH_FIELD],
}

export const dataBeachTableFormLogic = kea<dataBeachTableFormLogicType>([
    path(['scenes', 'data-management', 'database', 'dataBeachTableFormLogic']),
    props({} as DataBeachTableFormLogicProps),
    key((props) => props.dataBeachTable?.id ?? 'new'),

    forms(({ props }) => ({
        dataBeachTable: {
            defaults: (props.dataBeachTable ?? EMPTY_DATA_BEACH_TABLE) as DataBeachTableType,

            errors: (dataBeachTable: DataBeachTableType) => ({
                name: !dataBeachTable.name ? 'Must have a name' : undefined,
                engine: !dataBeachTable.engine ? 'Must have a engine' : undefined,
                fields: dataBeachTable.fields.map((field) => ({
                    name: !field.name ? 'Must have a name' : undefined,
                    type: !field.type ? 'Must have a type' : undefined,
                })),
            }),

            submit: async (dataBeachTable: DataBeachTableType, breakpoint) => {
                const { id, ...table } = dataBeachTable
                console.log(table)
                const newDataBeachTable = dataBeachTable.id
                    ? await api.dataBeachTables.update(dataBeachTable.id, table)
                    : await api.dataBeachTables.create(table)
                breakpoint()

                console.log(newDataBeachTable)
                lemonToast.success('Table saved')
            },

            showErrorsOnTouch: true,
        },
    })),

    selectors({
        fields: [(s) => [s.dataBeachTable], (dataBeachTable) => dataBeachTable?.fields ?? [{}]],
    }),
])
