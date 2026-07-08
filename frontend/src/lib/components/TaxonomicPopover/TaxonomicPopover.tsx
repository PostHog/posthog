import { Placement } from '@floating-ui/react'
import { useValues } from 'kea'
import { Ref, forwardRef, useEffect, useId, useState } from 'react'

import { IconX } from '@posthog/icons'

import { taxonomicTriggerWrapperClassName } from 'lib/components/TaxonomicFilter/menu/triggerLayout'
import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import {
    DataWarehousePopoverField,
    DefinitionPopoverRenderer,
    ExcludedProperties,
    SelectedProperties,
    TaxonomicFilterGroupType,
    TaxonomicFilterValue,
} from 'lib/components/TaxonomicFilter/types'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonButton, LemonButtonProps } from 'lib/lemon-ui/LemonButton'
import { LemonDropdown } from 'lib/lemon-ui/LemonDropdown'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { LocalFilter } from 'scenes/insights/filters/ActionFilter/entityFilterLogic'
import { MaxContextTaxonomicFilterOption } from 'scenes/max/maxTypes'

import { AnyDataNode, DatabaseSchemaField } from '~/queries/schema/schema-general'

import { taxonomicMenuPreferenceLogic } from './taxonomicMenuPreferenceLogic'
import { TaxonomicMenuToggle } from './TaxonomicMenuToggle'
import { TaxonomicPopoverMenu } from './TaxonomicPopoverMenu'

export interface TaxonomicPopoverProps<ValueType extends TaxonomicFilterValue = TaxonomicFilterValue> extends Omit<
    LemonButtonProps,
    'children' | 'onClick' | 'sideAction'
> {
    groupType: TaxonomicFilterGroupType
    value?: ValueType | null
    onChange: (value: ValueType, groupType: TaxonomicFilterGroupType, item: any) => void

    filter?: LocalFilter
    groupTypes?: TaxonomicFilterGroupType[]
    renderValue?: (value: ValueType) => JSX.Element | null
    eventNames?: string[]
    placeholder?: React.ReactNode
    placeholderClass?: string
    placement?: Placement
    /** Width of the popover. */
    width?: number
    schemaColumns?: DatabaseSchemaField[]
    allowClear?: boolean
    style?: React.CSSProperties
    closeOnChange?: boolean
    excludedProperties?: ExcludedProperties
    selectedProperties?: SelectedProperties
    metadataSource?: AnyDataNode
    showNumericalPropsOnly?: boolean
    dataWarehousePopoverFields?: DataWarehousePopoverField[]
    maxContextOptions?: MaxContextTaxonomicFilterOption[]
    allowNonCapturedEvents?: boolean
    sideIcon?: React.ReactElement | null
    definitionPopoverRenderer?: DefinitionPopoverRenderer
    suggestedFiltersLabel?: string
    enableKeywordShortcuts?: boolean
    selectingKeyOnly?: boolean
}

/** Like TaxonomicPopover, but convenient when you know you will only use string values */
export function TaxonomicStringPopover(props: TaxonomicPopoverProps<string>): JSX.Element {
    const value = props.value != null ? String(props.value) : undefined
    return (
        <TaxonomicPopover
            {...props}
            value={value}
            onChange={(value, groupType, item) => props.onChange?.(String(value), groupType, item)}
            renderValue={(v) => props.renderValue?.(String(v)) ?? <>{value}</>}
        />
    )
}

export const TaxonomicPopover = forwardRef(function TaxonomicPopover_<
    ValueType extends TaxonomicFilterValue = TaxonomicFilterValue,
>(
    {
        groupType,
        value,
        filter,
        onChange,
        renderValue,
        groupTypes,
        eventNames = [],
        placeholder = 'Please select',
        placeholderClass,
        allowClear = false,
        closeOnChange = true,
        excludedProperties,
        selectedProperties,
        metadataSource,
        schemaColumns,
        showNumericalPropsOnly,
        dataWarehousePopoverFields,
        maxContextOptions,
        allowNonCapturedEvents,
        definitionPopoverRenderer,
        suggestedFiltersLabel,
        enableKeywordShortcuts,
        selectingKeyOnly,
        width,
        placement,
        sideIcon,
        ...buttonPropsRest
    }: TaxonomicPopoverProps<ValueType>,
    ref: Ref<HTMLButtonElement>
): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { useNewMenu } = useValues(taxonomicMenuPreferenceLogic)
    const menuRebuildEnabled = !!featureFlags[FEATURE_FLAGS.TAXONOMIC_FILTER_MENU_REBUILD]

    const generatedKey = useId()
    const taxonomicFilterLogicKey = `taxonomic-popover-${generatedKey}`
    const [localValue, setLocalValue] = useState<ValueType>(value || ('' as ValueType))
    const [visible, setVisible] = useState(false)

    const isClearButtonShown = allowClear && !!localValue

    const buttonPropsFinal: Omit<LemonButtonProps, 'sideAction' | 'sideIcon'> = buttonPropsRest
    buttonPropsFinal.children = localValue ? (
        <span>{renderValue?.(localValue) ?? localValue}</span>
    ) : placeholder || placeholderClass ? (
        <span className={placeholderClass}>{placeholder}</span>
    ) : null
    buttonPropsFinal.onClick = () => setVisible(!visible)
    if (!buttonPropsFinal.type) {
        buttonPropsFinal.type = 'secondary'
    }
    if (localValue && !visible && !renderValue) {
        buttonPropsFinal.tooltip = String(localValue)
    }

    useEffect(() => {
        if (!buttonPropsFinal.loading) {
            setLocalValue(value || ('' as ValueType))
        }
    }, [value]) // oxlint-disable-line react-hooks/exhaustive-deps

    const legacyEl = (
        <LemonDropdown
            overlay={
                <TaxonomicFilter
                    taxonomicFilterLogicKey={taxonomicFilterLogicKey}
                    groupType={groupType}
                    value={value}
                    filter={filter}
                    onChange={({ type }, payload, item) => {
                        onChange?.(payload as ValueType, type, item)
                        if (closeOnChange) {
                            setVisible(false)
                        }
                    }}
                    taxonomicGroupTypes={groupTypes ?? [groupType]}
                    eventNames={eventNames}
                    schemaColumns={schemaColumns}
                    metadataSource={metadataSource}
                    excludedProperties={excludedProperties}
                    selectedProperties={selectedProperties}
                    showNumericalPropsOnly={showNumericalPropsOnly}
                    dataWarehousePopoverFields={dataWarehousePopoverFields}
                    maxContextOptions={maxContextOptions}
                    allowNonCapturedEvents={allowNonCapturedEvents}
                    definitionPopoverRenderer={definitionPopoverRenderer}
                    suggestedFiltersLabel={suggestedFiltersLabel}
                    enableKeywordShortcuts={enableKeywordShortcuts}
                    selectingKeyOnly={selectingKeyOnly}
                    width={width}
                />
            }
            matchWidth={false}
            actionable
            visible={visible}
            onClickOutside={() => {
                setVisible(false)
            }}
            placement={placement}
        >
            {isClearButtonShown ? (
                <LemonButton
                    sideAction={{
                        icon: <IconX />,
                        tooltip: 'Clear selection',
                        onClick: (e) => {
                            e.stopPropagation()
                            onChange?.('' as ValueType, groupType, null)
                            setLocalValue('' as ValueType)
                        },
                        divider: false,
                    }}
                    {...buttonPropsFinal}
                    ref={ref}
                />
            ) : (
                <LemonButton {...buttonPropsFinal} {...(sideIcon !== undefined && { sideIcon })} ref={ref} />
            )}
        </LemonDropdown>
    )

    if (!menuRebuildEnabled) {
        return legacyEl
    }

    // Menu-rebuild rollout — the rebuilt menu is rendered by default; a
    // visible toggle (persisted per-user via `taxonomicMenuPreferenceLogic`)
    // lets the user swap back to the classic filter and forward again.
    // Gated by `taxonomic-filter-menu-rebuild`.
    //
    // The rebuilt menu carries its own toggle (inside its trigger wrapper),
    // so it's rendered with no extra DOM around it — the trigger inherits
    // the call site's layout exactly. The legacy path needs a thin
    // positioned wrapper to host the floating toggle.
    //
    // The rebuilt menu can't honour these legacy capabilities, so a call site
    // that needs any of them stays on the classic filter (still with the
    // toggle) — no behaviour is silently lost:
    //   - `allowClear`            — the clear (X) affordance
    //   - `closeOnChange={false}` — keep-open-after-select
    //   - a forwarded `ref`       — the rebuilt trigger can't receive it
    //
    // `selectingKeyOnly` (key-based onChange) and `definitionPopoverRenderer`
    // (the hover definition card) are superseded by the rebuilt menu itself —
    // its onChange already commits the resolved key and its preview pane
    // replaces the definition popover — so they no longer gate the new menu.
    const newMenuSupportsCallSite = !allowClear && closeOnChange && ref == null
    if (useNewMenu && newMenuSupportsCallSite) {
        return (
            <TaxonomicPopoverMenu<ValueType>
                groupType={groupType}
                value={value}
                groupTypes={groupTypes}
                onChange={onChange}
                renderValue={renderValue}
                placeholder={placeholder}
                placeholderClass={placeholderClass}
                eventNames={eventNames}
                schemaColumns={schemaColumns}
                metadataSource={metadataSource}
                excludedProperties={excludedProperties}
                selectedProperties={selectedProperties}
                showNumericalPropsOnly={showNumericalPropsOnly}
                dataWarehousePopoverFields={dataWarehousePopoverFields}
                maxContextOptions={maxContextOptions}
                allowNonCapturedEvents={allowNonCapturedEvents}
                suggestedFiltersLabel={suggestedFiltersLabel}
                enableKeywordShortcuts={enableKeywordShortcuts}
                triggerButtonProps={{
                    icon: buttonPropsRest.icon,
                    sideIcon: sideIcon,
                    fullWidth: buttonPropsRest.fullWidth,
                    size: buttonPropsRest.size,
                    type: buttonPropsRest.type ?? 'secondary',
                    className: buttonPropsRest.className,
                    disabledReason: buttonPropsRest.disabledReason,
                }}
            />
        )
    }
    return (
        <span className={taxonomicTriggerWrapperClassName(buttonPropsRest.fullWidth)}>
            {legacyEl}
            <TaxonomicMenuToggle />
        </span>
    )
}) as <ValueType extends TaxonomicFilterValue = TaxonomicFilterValue>(
    props: TaxonomicPopoverProps<ValueType> & { ref?: Ref<HTMLButtonElement> }
) => JSX.Element
