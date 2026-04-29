import './TaxonomicFilter.scss'

import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import { forwardRef, useEffect, useMemo, useRef, useState } from 'react'

import { Link } from '@posthog/lemon-ui'

import {
    CategoryDropdownVariant,
    resolveCategoryDropdownVariant,
    TaxonomicFilterGroupType,
    TaxonomicFilterLogicProps,
    TaxonomicFilterProps,
} from 'lib/components/TaxonomicFilter/types'
import { FEATURE_FLAGS } from 'lib/constants'
import { Icon123 } from 'lib/lemon-ui/icons'
import { LemonInput, LemonInputPropsText } from 'lib/lemon-ui/LemonInput/LemonInput'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { CategoryDropdown } from './CategoryDropdown'
import { InfiniteSelectResults } from './InfiniteSelectResults'
import { defaultDataWarehousePopoverFields, taxonomicFilterLogic } from './taxonomicFilterLogic'

let uniqueMemoizedIndex = 0

export function TaxonomicFilter({
    taxonomicFilterLogicKey: taxonomicFilterLogicKeyInput,
    groupType,
    value,
    filter,
    onChange,
    onClose,
    taxonomicGroupTypes,
    optionsFromProp,
    metadataSource,
    eventNames,
    schemaColumns,
    schemaColumnsLoading,
    height,
    width,
    excludedProperties,
    selectedProperties,
    popoverEnabled = true,
    selectFirstItem = true,
    propertyAllowList,
    hideBehavioralCohorts,
    showNumericalPropsOnly,
    dataWarehousePopoverFields = defaultDataWarehousePopoverFields,
    maxContextOptions,
    allowNonCapturedEvents = false,
    hogQLGlobals,
    hogQLExpressionShowBreakdownLabelHint,
    definitionPopoverRenderer,
    minSearchQueryLength,
    suggestedFiltersLabel,
    hideSearchInput,
    searchQuery: controlledSearchQuery,
    enableKeywordShortcuts,
}: TaxonomicFilterProps): JSX.Element {
    // Generate a unique key for each unique TaxonomicFilter that's rendered
    const taxonomicFilterLogicKey = useMemo(
        () => taxonomicFilterLogicKeyInput || `taxonomic-filter-${uniqueMemoizedIndex++}`,
        [taxonomicFilterLogicKeyInput]
    )

    const searchInputRef = useRef<HTMLInputElement | null>(null)
    const focusInput = (): void => searchInputRef.current?.focus()

    const { featureFlags } = useValues(featureFlagLogic)
    const categoryDropdownVariant = resolveCategoryDropdownVariant(
        featureFlags[FEATURE_FLAGS.TAXONOMIC_FILTER_CATEGORY_DROPDOWN]
    )
    const resolvedSuggestedFiltersLabel =
        suggestedFiltersLabel ?? (categoryDropdownVariant === 'control' ? 'Suggestions' : 'All')

    const taxonomicFilterLogicProps: TaxonomicFilterLogicProps = {
        taxonomicFilterLogicKey,
        groupType,
        value,
        filter,
        onChange,
        taxonomicGroupTypes,
        optionsFromProp,
        eventNames,
        schemaColumns,
        schemaColumnsLoading,
        popoverEnabled,
        selectFirstItem,
        excludedProperties,
        selectedProperties,
        metadataSource,
        propertyAllowList,
        hideBehavioralCohorts,
        showNumericalPropsOnly,
        dataWarehousePopoverFields,
        autoSelectItem: true,
        allowNonCapturedEvents,
        maxContextOptions,
        hogQLGlobals,
        hogQLExpressionShowBreakdownLabelHint,
        minSearchQueryLength,
        suggestedFiltersLabel: resolvedSuggestedFiltersLabel,
        enableKeywordShortcuts,
    }

    const logic = taxonomicFilterLogic(taxonomicFilterLogicProps)
    const { activeTab } = useValues(logic)
    const { setSearchQuery } = useActions(logic)
    const [refReady, setRefReady] = useState(false)

    useEffect(() => {
        if (controlledSearchQuery !== undefined) {
            setSearchQuery(controlledSearchQuery)
        }
    }, [controlledSearchQuery, setSearchQuery])

    useEffect(() => {
        if (groupType !== TaxonomicFilterGroupType.HogQLExpression) {
            window.setTimeout(() => focusInput(), 1)
        }
    }, [groupType])

    const taxonomicFilterRef = useRef<HTMLInputElement | null>(null)
    useEffect(() => {
        if (taxonomicFilterRef.current) {
            setRefReady(true)
        }
    }, [taxonomicFilterRef.current])

    const style = {
        ...(width ? { width } : {}),
        ...(height ? { height } : {}),
    }

    return (
        <BindLogic logic={taxonomicFilterLogic} props={taxonomicFilterLogicProps}>
            <div
                ref={taxonomicFilterRef}
                className={clsx(
                    'taxonomic-filter',
                    taxonomicGroupTypes.length === 1 && 'one-taxonomic-tab',
                    !width && 'force-minimum-width'
                )}
                data-attr={taxonomicFilterLogicKey}
                // eslint-disable-next-line react/forbid-dom-props
                style={style}
            >
                {!hideSearchInput &&
                (activeTab !== TaxonomicFilterGroupType.HogQLExpression || taxonomicGroupTypes.length > 1) ? (
                    <div className="relative">
                        <TaxonomicFilterSearchInput
                            searchInputRef={searchInputRef}
                            onClose={onClose}
                            categoryDropdownVariant={categoryDropdownVariant}
                            eventName={eventNames?.[0]}
                            focusInput={focusInput}
                        />
                    </div>
                ) : null}
                {refReady && (
                    <InfiniteSelectResults
                        focusInput={focusInput}
                        taxonomicFilterLogicProps={taxonomicFilterLogicProps}
                        popupAnchorElement={taxonomicFilterRef.current}
                        definitionPopoverRenderer={definitionPopoverRenderer}
                        categoryDropdownVariant={categoryDropdownVariant}
                    />
                )}
            </div>
        </BindLogic>
    )
}

export const TaxonomicFilterSearchInput = forwardRef<
    HTMLInputElement,
    {
        searchInputRef: React.Ref<HTMLInputElement> | null
        onClose: TaxonomicFilterProps['onClose']
        categoryDropdownVariant?: CategoryDropdownVariant
        eventName?: string
        focusInput?: () => void
    } & Pick<
        LemonInputPropsText,
        'onClick' | 'size' | 'prefix' | 'fullWidth' | 'onChange' | 'autoFocus' | 'placeholder'
    >
>(function UniversalSearchInput(
    {
        searchInputRef,
        onClose,
        onChange,
        autoFocus = true,
        placeholder,
        categoryDropdownVariant = 'control',
        eventName,
        focusInput,
        prefix,
        ...props
    },
    ref
): JSX.Element {
    const { searchQuery, searchPlaceholder, showNumericalPropsOnly } = useValues(taxonomicFilterLogic)
    const {
        setSearchQuery: setTaxonomicSearchQuery,
        recordPaste,
        moveUp,
        moveDown,
        tabLeft,
        tabRight,
        selectSelected,
    } = useActions(taxonomicFilterLogic)

    const _onChange = (query: string): void => {
        setTaxonomicSearchQuery(query)
        onChange?.(query)
    }

    const categoriesAreInDropdown = categoryDropdownVariant !== 'control'
    const categoryDropdown = categoriesAreInDropdown ? (
        <CategoryDropdown variant={categoryDropdownVariant} eventName={eventName} onAfterChange={focusInput} />
    ) : null

    return (
        <LemonInput
            {...props}
            ref={ref}
            data-attr="taxonomic-filter-searchfield"
            type="search"
            fullWidth
            placeholder={placeholder ?? `Search ${searchPlaceholder}`}
            value={searchQuery}
            prefix={prefix}
            onPaste={(e) => {
                const pasted = e.clipboardData?.getData('text') ?? ''
                if (pasted.length > 0) {
                    recordPaste(pasted.length)
                }
            }}
            suffix={
                <>
                    {categoryDropdown}
                    {showNumericalPropsOnly && (
                        <Tooltip
                            title={
                                <span>
                                    This filter only shows numerical properties. If you're not seeing your property
                                    here, make sure it's properly set as numeric in the{' '}
                                    <Link to={urls.propertyDefinitions()} target="_blank">
                                        Property Definitions
                                    </Link>{' '}
                                    page.
                                </span>
                            }
                        >
                            <span>
                                <Icon123 style={{ fontSize: '1.2rem' }} className="text-secondary" />
                            </span>
                        </Tooltip>
                    )}
                </>
            }
            onKeyDown={(e) => {
                let shouldPreventDefault = true
                switch (e.key) {
                    case 'ArrowUp':
                        moveUp()
                        break
                    case 'ArrowDown':
                        moveDown()
                        break
                    case 'Tab':
                        if (categoriesAreInDropdown) {
                            shouldPreventDefault = false
                            break
                        }
                        e.shiftKey ? tabLeft() : tabRight()
                        break
                    case 'Enter':
                        selectSelected()
                        break
                    case 'Escape':
                        _onChange('')
                        onClose?.()
                        break
                    default:
                        shouldPreventDefault = false
                }
                if (shouldPreventDefault) {
                    e.preventDefault()
                }
            }}
            inputRef={searchInputRef}
            onChange={_onChange}
            autoFocus={autoFocus}
        />
    )
})
