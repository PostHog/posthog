import './TaxonomicFilter.scss'

import { IconKeyboard } from '@posthog/icons'
import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import {
    TaxonomicFilterGroupType,
    TaxonomicFilterLogicProps,
    TaxonomicFilterProps,
} from 'lib/components/TaxonomicFilter/types'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { useEffect, useMemo, useRef } from 'react'

import { InfiniteSelectResults } from './InfiniteSelectResults'
import { taxonomicFilterLogic } from './taxonomicFilterLogic'

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
    height,
    width,
    excludedProperties,
    popoverEnabled = true,
    selectFirstItem = true,
    propertyAllowList,
}: TaxonomicFilterProps): JSX.Element {
    // Generate a unique key for each unique TaxonomicFilter that's rendered
    const taxonomicFilterLogicKey = useMemo(
        () => taxonomicFilterLogicKeyInput || `taxonomic-filter-${uniqueMemoizedIndex++}`,
        [taxonomicFilterLogicKeyInput]
    )

    const searchInputRef = useRef<HTMLInputElement | null>(null)
    const focusInput = (): void => searchInputRef.current?.focus()

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
        popoverEnabled,
        selectFirstItem,
        excludedProperties,
        metadataSource,
        propertyAllowList,
    }

    const logic = taxonomicFilterLogic(taxonomicFilterLogicProps)
    const { searchQuery, searchPlaceholder, activeTab } = useValues(logic)
    const { setSearchQuery, moveUp, moveDown, tabLeft, tabRight, selectSelected } = useActions(logic)

    useEffect(() => {
        if (groupType !== TaxonomicFilterGroupType.HogQLExpression) {
            window.setTimeout(() => focusInput(), 1)
        }
    }, [])

    const style = {
        ...(width ? { width } : {}),
        ...(height ? { height } : {}),
    }

    const taxonomicFilterRef = useRef<HTMLInputElement | null>(null)

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
                {activeTab !== TaxonomicFilterGroupType.HogQLExpression || taxonomicGroupTypes.length > 1 ? (
                    <div className="relative">
                        <LemonInput
                            data-attr="taxonomic-filter-searchfield"
                            type="search"
                            fullWidth
                            placeholder={`Search ${searchPlaceholder}`}
                            value={searchQuery}
                            suffix={
                                <Tooltip
                                    title={
                                        <>
                                            You can easily navigate between tabs with your keyboard.{' '}
                                            <div>
                                                Use <b>tab</b> to move to the next tab.
                                            </div>
                                            <div>
                                                Use <b>shift + tab</b> to move to the previous tab.
                                            </div>
                                        </>
                                    }
                                >
                                    <IconKeyboard style={{ fontSize: '1.2rem' }} className="text-muted-alt" />
                                </Tooltip>
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
                                        e.shiftKey ? tabLeft() : tabRight()
                                        break
                                    case 'Enter':
                                        selectSelected()
                                        break
                                    case 'Escape':
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
                            onChange={(newValue) => setSearchQuery(newValue)}
                        />
                    </div>
                ) : null}
                <InfiniteSelectResults
                    focusInput={focusInput}
                    taxonomicFilterLogicProps={taxonomicFilterLogicProps}
                    popupAnchorElement={taxonomicFilterRef.current}
                />
            </div>
        </BindLogic>
    )
}
