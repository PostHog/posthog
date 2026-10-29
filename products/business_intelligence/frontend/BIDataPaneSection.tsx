import { useMountedLogic, useValues } from 'kea'

import { BIField } from '~/queries/schema/schema-business-intelligence'

import { BIDataPaneField } from './BIDataPaneField'
import { biEditorLogic } from './biEditorLogic'
import { BIPropertyFieldGroup } from './BIPropertyFieldGroup'
import { getBIPropertyTarget } from './biPropertyFields'
import { biSourceMetadataLogic } from './biSourceMetadataLogic'

export function BIDataPaneSection({
    title,
    fields,
    measure,
    emptyText,
    path = [],
    tableName,
}: {
    title?: string
    fields: BIField[]
    measure: boolean
    emptyText: string
    path?: string[]
    tableName?: string
}): JSX.Element {
    const logic = useMountedLogic(biEditorLogic)
    const { dataPaneSearch, config, allTables, databaseConnectionId } = useValues(logic)
    const table =
        !config.source?.connectionId && !databaseConnectionId
            ? allTables.find(
                  (candidate) => candidate.name === (tableName ?? (path.length ? undefined : config.source?.table))
              )
            : undefined
    const { annotations, annotationsError } = useValues(biSourceMetadataLogic({ table }))
    return (
        <div className="flex flex-col">
            {title ? <div className="px-2 pb-1 pt-2 text-xs font-semibold text-secondary">{title}</div> : null}
            {fields.length === 0 ? <span className="px-2 text-xs text-tertiary">{emptyText}</span> : null}
            {fields.map((field) =>
                getBIPropertyTarget(field) ? (
                    <BIPropertyFieldGroup
                        key={field.id}
                        field={field}
                        path={path}
                        tabId={logic.props.tabId}
                        dataPaneSearch={dataPaneSearch}
                    />
                ) : (
                    <BIDataPaneField
                        key={field.id}
                        field={field}
                        measure={measure}
                        path={path}
                        description={
                            field.localDefinition || annotationsError
                                ? undefined
                                : annotations[path.length ? field.name.slice(path.join('.').length + 1) : field.name]
                        }
                    />
                )
            )}
        </div>
    )
}
