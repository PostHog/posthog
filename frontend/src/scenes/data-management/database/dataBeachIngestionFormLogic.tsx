import { kea, key, props, path, selectors } from 'kea'
import { forms } from 'kea-forms'
import { DataBeachTableType } from '~/types'

import type { dataBeachIngestionFormLogicType } from './dataBeachIngestionFormLogicType'
import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/lemonToast'

export interface DataBeachIngestionFormLogicProps {
    dataBeachTable: DataBeachTableType | null
    onClose?: () => void
}

export interface IngestionForm {
    rows: Record<string, any>[]
}

export const dataBeachIngestionFormLogic = kea<dataBeachIngestionFormLogicType>([
    path(['scenes', 'data-management', 'database', 'dataBeachIngestionFormLogic']),
    props({} as DataBeachIngestionFormLogicProps),
    key((props) => props.dataBeachTable?.id ?? 'disabled'),

    forms(({ props }) => ({
        ingestionForm: {
            defaults: { rows: [{}] } as IngestionForm,
            submit: async (ingestionForm) => {
                if (!props.dataBeachTable?.id) {
                    return
                }
                const { rows } = ingestionForm
                try {
                    await api.dataBeachTables.insert(props.dataBeachTable.id, rows)
                    lemonToast.success(`${rows.length} row${rows.length === 1 ? '' : 's'} inserted`)
                    props.onClose?.()
                } catch (error: any) {
                    lemonToast.error(String(error?.detail ?? error?.message ?? error?.status ?? error))
                }
            },
        },
    })),

    selectors({
        rows: [(s) => [s.ingestionForm], (ingestionForm): any[] => ingestionForm?.rows ?? [{}]],
        fields: [(_, p) => [p.dataBeachTable], (dataBeachTable) => dataBeachTable?.fields ?? []],
    }),
])
