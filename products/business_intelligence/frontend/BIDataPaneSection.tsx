import { useMountedLogic } from 'kea'

import { BIField } from '~/queries/schema/schema-business-intelligence'

import { BIDataPaneField } from './BIDataPaneField'
import { biEditorLogic } from './biEditorLogic'
import { BIPropertyFieldGroup } from './BIPropertyFieldGroup'
import { getBIPropertyTarget } from './biPropertyFields'

export function BIDataPaneSection({
    title,
    fields,
    measure,
    emptyText,
    path = [],
}: {
    title?: string
    fields: BIField[]
    measure: boolean
    emptyText: string
    path?: string[]
}): JSX.Element {
    const logic = useMountedLogic(biEditorLogic)
    return (
        <div className="flex flex-col">
            {title ? <div className="px-2 pb-1 pt-2 text-xs font-semibold text-secondary">{title}</div> : null}
            {fields.length === 0 ? <span className="px-2 text-xs text-tertiary">{emptyText}</span> : null}
            {fields.map((field) =>
                getBIPropertyTarget(field) ? (
                    <BIPropertyFieldGroup key={field.id} field={field} path={path} tabId={logic.props.tabId} />
                ) : (
                    <BIDataPaneField key={field.id} field={field} measure={measure} path={path} />
                )
            )}
        </div>
    )
}
