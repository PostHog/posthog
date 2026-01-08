import { useMemo } from 'react'

import { LemonButton, LemonModal, LemonSelect } from '@posthog/lemon-ui'

import { SchemaMap } from '~/queries/schema/schema-general'

export interface SchemaMapModalProps {
    isOpen: boolean
    onClose: () => void
    title: string
    goalName: string
    schemaMap: SchemaMap
    onSchemaMapChange: (schemaMap: SchemaMap) => void
    onConfirm: () => void
    confirmText: string
    availableColumns: string[]
}

export function SchemaMapModal({
    isOpen,
    onClose,
    title,
    schemaMap,
    onSchemaMapChange,
    onConfirm,
    confirmText,
    availableColumns,
}: SchemaMapModalProps): JSX.Element {
    const columnOptions = useMemo(() => {
        return availableColumns.map((col) => ({ value: col, label: col }))
    }, [availableColumns])

    const isValid = schemaMap.utm_campaign_name && schemaMap.utm_source_name

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            title={title}
            footer={
                <>
                    <LemonButton onClick={onClose}>Cancel</LemonButton>
                    <LemonButton type="primary" onClick={onConfirm} disabled={!isValid}>
                        {confirmText}
                    </LemonButton>
                </>
            }
        >
            <div className="space-y-4">
                <p className="text-muted">
                    Select which columns in your data warehouse table contain the UTM attribution data.
                </p>

                <div className="space-y-3">
                    <div>
                        <label className="text-sm font-medium mb-1 block">UTM Campaign column</label>
                        <LemonSelect
                            value={schemaMap.utm_campaign_name || null}
                            onChange={(value) =>
                                onSchemaMapChange({ ...schemaMap, utm_campaign_name: value || undefined })
                            }
                            options={columnOptions}
                            placeholder="Select column..."
                            className="w-full"
                        />
                    </div>

                    <div>
                        <label className="text-sm font-medium mb-1 block">UTM Source column</label>
                        <LemonSelect
                            value={schemaMap.utm_source_name || null}
                            onChange={(value) =>
                                onSchemaMapChange({ ...schemaMap, utm_source_name: value || undefined })
                            }
                            options={columnOptions}
                            placeholder="Select column..."
                            className="w-full"
                        />
                    </div>
                </div>
            </div>
        </LemonModal>
    )
}
