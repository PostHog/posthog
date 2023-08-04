import { actions, kea, key, path, props, reducers } from 'kea'
import type { notebookSettingsWidgetLogicType } from './notebookSettingsWidgetLogicType'

export type NotebookSettingsWidgetLogicProps = {
    id: string
}

export const notebookSettingsWidgetLogic = kea<notebookSettingsWidgetLogicType>([
    props({} as NotebookSettingsWidgetLogicProps),
    path((key) => ['scenes', 'notebooks', 'notebooks', 'notebookSettingsWidgetLogic', key]),
    key(({ id }) => id),
    actions({
        setIsExpanded: (expanded: boolean) => ({ expanded }),
    }),
    reducers(({}) => ({
        isExpanded: [
            true,
            { persist: true },
            {
                setIsExpanded: (_, { expanded }) => expanded,
            },
        ],
    })),
])
