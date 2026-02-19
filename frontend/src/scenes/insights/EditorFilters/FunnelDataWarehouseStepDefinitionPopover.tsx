import { useActions, useValues } from 'kea'
import { Fragment } from 'react'

import { IconInfo } from '@posthog/icons'
import { LemonButton, LemonSelect } from '@posthog/lemon-ui'

import { definitionPopoverLogic } from 'lib/components/DefinitionPopover/definitionPopoverLogic'
import { HogQLDropdown } from 'lib/components/HogQLDropdown/HogQLDropdown'
import { taxonomicFilterLogic } from 'lib/components/TaxonomicFilter/taxonomicFilterLogic'
import {
    DataWarehousePopoverField,
    DefinitionPopoverRendererProps,
    TaxonomicFilterGroupType,
} from 'lib/components/TaxonomicFilter/types'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { cn } from 'lib/utils/css-classes'
import { DataWarehouseTableForInsight } from 'scenes/data-warehouse/types'

export function FunnelDataWarehouseStepDefinitionPopover({
    item,
    group,
    defaultView,
}: DefinitionPopoverRendererProps): JSX.Element | null {
    const { localDefinition } = useValues(definitionPopoverLogic)
    const { setLocalDefinition } = useActions(definitionPopoverLogic)
    const { dataWarehousePopoverFields } = useValues(taxonomicFilterLogic)
    const { selectItem } = useActions(taxonomicFilterLogic)

    if (group.type !== TaxonomicFilterGroupType.DataWarehouse) {
        return defaultView
    }

    const definition = ('fields' in localDefinition ? localDefinition : item) as DataWarehouseTableForInsight
    const columnOptions = Object.values(definition?.fields ?? {}).map((column) => ({
        label: `${column.name} (${column.type})`,
        value: column.name,
        type: column.type,
    }))
    const hogQLOption = { label: 'SQL Expression', value: '' }
    const itemValue = localDefinition ? group?.getValue?.(localDefinition) : null

    const isUsingHogQLExpression = (value: string | undefined): boolean => {
        if (value === undefined) {
            return false
        }
        const column = Object.values(definition?.fields ?? {}).find((n) => n.name === value)
        return !column
    }

    if (!definition || dataWarehousePopoverFields.length === 0) {
        return <></>
    }

    return (
        <form className="definition-popover-data-warehouse-schema-form">
            <div className="flex flex-col justify-between gap-4">
                <div className="flex flex-col deprecated-space-y-4">
                    {dataWarehousePopoverFields.map(
                        ({ key, label, description, allowHogQL, hogQLOnly, tableName, optional, type }) => {
                            const fieldValue = key in localDefinition ? localDefinition[key] : undefined
                            const isHogQL = isUsingHogQLExpression(fieldValue)

                            return (
                                <Fragment key={key}>
                                    <label className="definition-popover-edit-form-label" htmlFor={key}>
                                        <span
                                            className={cn('label-text', {
                                                'font-semibold': !optional,
                                            })}
                                        >
                                            {label}
                                            {!optional && <span className="text-muted">&nbsp;*</span>}
                                        </span>
                                        {description && (
                                            <Tooltip title={description}>
                                                &nbsp;
                                                <IconInfo className="ml-1" />
                                            </Tooltip>
                                        )}
                                    </label>
                                    {!hogQLOnly && (
                                        <LemonSelect
                                            fullWidth
                                            allowClear={!!optional}
                                            value={isHogQL ? '' : fieldValue}
                                            options={[
                                                ...columnOptions.filter((col) => !type || col.type === type),
                                                ...(allowHogQL ? [hogQLOption] : []),
                                            ]}
                                            onChange={(value: string | null) => setLocalDefinition({ [key]: value })}
                                        />
                                    )}
                                    {((allowHogQL && isHogQL) || hogQLOnly) && (
                                        <HogQLDropdown
                                            hogQLValue={fieldValue || ''}
                                            tableName={tableName || definition.name}
                                            onHogQLValueChange={(value) => setLocalDefinition({ [key]: value })}
                                        />
                                    )}
                                </Fragment>
                            )
                        }
                    )}
                </div>
                <div className="flex justify-end">
                    <LemonButton
                        onClick={() => {
                            selectItem(group, itemValue ?? null, localDefinition, undefined)
                        }}
                        disabledReason={
                            dataWarehousePopoverFields.every(
                                ({ key, optional }: DataWarehousePopoverField) =>
                                    optional || (key in localDefinition && localDefinition[key])
                            )
                                ? null
                                : 'All required field mappings must be specified'
                        }
                        type="primary"
                    >
                        Select
                    </LemonButton>
                </div>
            </div>
        </form>
    )
}
