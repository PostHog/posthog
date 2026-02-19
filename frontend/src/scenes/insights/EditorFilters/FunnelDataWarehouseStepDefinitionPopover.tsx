import { useActions, useValues } from 'kea'
import { Fragment } from 'react'

import { IconInfo } from '@posthog/icons'
import { LemonButton, LemonSelect } from '@posthog/lemon-ui'

import { HogQLDropdown } from 'lib/components/HogQLDropdown/HogQLDropdown'
import {
    DataWarehousePopoverField,
    DefinitionPopoverRendererProps,
    TaxonomicFilterGroupType,
} from 'lib/components/TaxonomicFilter/types'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { cn } from 'lib/utils/css-classes'

import { funnelDataWarehouseStepDefinitionPopoverLogic } from './funnelDataWarehouseStepDefinitionPopoverLogic'

export function FunnelDataWarehouseStepDefinitionPopover({
    item,
    group,
    defaultView,
}: DefinitionPopoverRendererProps): JSX.Element | null {
    const logic = funnelDataWarehouseStepDefinitionPopoverLogic({ item, group })
    const {
        localDefinition,
        dataWarehousePopoverFields,
        definition,
        columnOptions,
        hogQLOption,
        selectionDisabledReason,
        isUsingHogQLExpression,
    } = useValues(logic)
    const { setFieldValue, selectDataWarehouseStep } = useActions(logic)

    if (group.type !== TaxonomicFilterGroupType.DataWarehouse) {
        return defaultView
    }

    if (!definition || dataWarehousePopoverFields.length === 0) {
        return <></>
    }

    return (
        <form className="definition-popover-data-warehouse-schema-form">
            <div className="flex flex-col justify-between gap-4">
                <div className="flex flex-col deprecated-space-y-4">
                    {dataWarehousePopoverFields.map(
                        ({
                            key,
                            label,
                            description,
                            allowHogQL,
                            hogQLOnly,
                            tableName,
                            optional,
                            type,
                        }: DataWarehousePopoverField) => {
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
                                                ...columnOptions.filter(
                                                    (col: { type: string }) => !type || col.type === type
                                                ),
                                                ...(allowHogQL ? [hogQLOption] : []),
                                            ]}
                                            onChange={(value: string | null) => setFieldValue(key, value)}
                                        />
                                    )}
                                    {((allowHogQL && isHogQL) || hogQLOnly) && (
                                        <HogQLDropdown
                                            hogQLValue={fieldValue || ''}
                                            tableName={tableName || definition.name}
                                            onHogQLValueChange={(value) => setFieldValue(key, value)}
                                        />
                                    )}
                                </Fragment>
                            )
                        }
                    )}
                </div>
                <div className="flex justify-end">
                    <LemonButton
                        onClick={selectDataWarehouseStep}
                        disabledReason={selectionDisabledReason}
                        type="primary"
                    >
                        Select
                    </LemonButton>
                </div>
            </div>
        </form>
    )
}
