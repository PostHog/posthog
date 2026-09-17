import './TaxonomicFilter.scss'

import clsx from 'clsx'
import { BindLogic, batchChanges, useActions, useValues } from 'kea'
import { forwardRef, useEffect, useId, useRef, useState } from 'react'

import { Link } from '@posthog/lemon-ui'

import {
    TaxonomicFilterGroupType,
    TaxonomicFilterLogicProps,
    TaxonomicFilterProps,
} from 'lib/components/TaxonomicFilter/types'
import { Icon123 } from 'lib/lemon-ui/icons'
import { LemonInput, LemonInputPropsText } from 'lib/lemon-ui/LemonInput/LemonInput'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { urls } from 'scenes/urls'

import { CategoryDropdown } from './CategoryDropdown'
import { InfiniteSelectResults } from './InfiniteSelectResults'
import { defaultDataWarehousePopoverFields, taxonomicFilterLogic } from './taxonomicFilterLogic'

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
    includeHiddenEvents,
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
    keepSearchOnSelect,
    enableKeywordShortcuts,
    excludedOperators,
    selectingKeyOnly,
    collapseUrlsToContainsRow,
}: TaxonomicFilterProps): JSX.Element {
    const generatedKey = useId()
    const taxonomicFilterLogicKey = taxonomicFilterLogicKeyInput || `taxonomic-filter-${generatedKey}`

    const searchInputRef = useRef<HTMLInputElement | null>(null)
    const focusInput = (): void => searchInputRef.current?.focus()

    const resolvedSuggestedFiltersLabel = suggestedFiltersLabel ?? 'All'

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
        includeHiddenEvents,
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
        keepSearchOnSelect,
        enableKeywordShortcuts,
        excludedOperators,
        selectingKeyOnly,
        collapseUrlsToContainsRow,
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
    }, [])

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
                    '@container',
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
        eventName?: string
        focusInput?: () => void
    } & Pick<
        LemonInputPropsText,
        'onClick' | 'size' | 'prefix' | 'fullWidth' | 'onChange' | 'autoFocus' | 'placeholder'
    >
>(function UniversalSearchInput(
    { searchInputRef, onClose, onChange, autoFocus = true, placeholder, eventName, focusInput, prefix, ...props },
    ref
): JSX.Element {
    const { searchQuery, searchPlaceholder, showNumericalPropsOnly } = useValues(taxonomicFilterLogic)
    const {
        setSearchQuery: setTaxonomicSearchQuery,
        markUserInteraction,
        recordPaste,
        moveUp,
        moveDown,
        selectSelected,
    } = useActions(taxonomicFilterLogic)

    const _onChange = (query: string): void => {
        // Batch the search query update to reduce re-renders while keeping the controlled input responsive.
        batchChanges(() => setTaxonomicSearchQuery(query))
        // Only the input's onChange path counts as user interaction. The controlled-prop
        // useEffect above also calls setSearchQuery directly, but that's programmatic and
        // shouldn't unmute the `taxonomic filter closed` capture — keep this dispatch separate.
        markUserInteraction()
        onChange?.(query)
    }

    const categoryDropdown = <CategoryDropdown eventName={eventName} onAfterChange={focusInput} joinedToInput />

    return (
        <LemonInput
            {...props}
            ref={ref}
            className="TaxonomicFilter__search-input--with-category @container"
            data-attr="taxonomic-filter-searchfield"
            type="search"
            suffixAfterClear
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
                            interactive
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
                        shouldPreventDefault = false
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
