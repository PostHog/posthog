import { kea, key, props, path, selectors } from 'kea'
import { forms } from 'kea-forms'
import { DataBeachTableType } from '~/types'

import type { dataBeachIngestionFormLogicType } from './dataBeachIngestionFormLogicType'

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

    forms(() => ({
        ingestionForm: {
            defaults: { rows: [{}] } as IngestionForm,
            submit: async (ingestionForm) => {
                const { rows } = ingestionForm
                console.log({ rows })
            },
        },
    })),

    selectors({
        rows: [(s) => [s.ingestionForm], (ingestionForm): any[] => ingestionForm?.rows ?? [{}]],
        fields: [(_, p) => [p.dataBeachTable], (dataBeachTable) => dataBeachTable?.fields ?? []],
    }),
])
