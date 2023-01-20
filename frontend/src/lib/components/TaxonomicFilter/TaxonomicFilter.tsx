import './TaxonomicFilter.scss'
import { useEffect, useMemo, useRef } from 'react'
import { BindLogic, useActions, useValues } from 'kea'
import { InfiniteSelectResults } from './InfiniteSelectResults'
import { taxonomicFilterLogic } from './taxonomicFilterLogic'
import {
    TaxonomicFilterGroupType,
    TaxonomicFilterLogicProps,
    TaxonomicFilterProps,
} from 'lib/components/TaxonomicFilter/types'
import { LemonInput } from 'lib/components/LemonInput/LemonInput'
import { IconKeyboard } from '../icons'
import { Tooltip } from '../Tooltip'
import clsx from 'clsx'

let uniqueMemoizedIndex = 0

export function TaxonomicFilter({
    taxonomicFilterLogicKey: taxonomicFilterLogicKeyInput,
    groupType,
    value,
    onChange,
    onClose,
    taxonomicGroupTypes,
    optionsFromProp,
    eventNames,
    height,
    width,
    excludedProperties,
    popoverEnabled = true,
    selectFirstItem = true,
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
        onChange,
        taxonomicGroupTypes,
        optionsFromProp,
        eventNames,
        popoverEnabled,
        selectFirstItem,
        excludedProperties,
    }

    const logic = taxonomicFilterLogic(taxonomicFilterLogicProps)
    const { searchQuery, searchPlaceholder } = useValues(logic)
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

    return (
        <BindLogic logic={taxonomicFilterLogic} props={taxonomicFilterLogicProps}>
            <div
                className={clsx(
                    'taxonomic-filter',
                    taxonomicGroupTypes.length === 1 && 'one-taxonomic-tab',
                    !width && 'force-minimum-width'
                )}
                style={style}
            >
                <div style={{ position: 'relative' }}>
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
                                            Use <b>tab</b> or <b>right arrow</b> to move to the next tab.
                                        </div>
                                        <div>
                                            Use <b>shift + tab</b> or <b>left arrow</b> to move to the previous tab.
                                        </div>
                                    </>
                                }
                            >
                                <IconKeyboard style={{ fontSize: '1.2rem' }} className="text-muted-alt" />
                            </Tooltip>
                        }
                        onKeyDown={(e) => {
                            if (e.key === 'ArrowUp') {
                                e.preventDefault()
                                moveUp()
                            }
                            if (e.key === 'ArrowDown') {
                                e.preventDefault()
                                moveDown()
                            }
                            if (e.key === 'Tab') {
                                e.preventDefault()
                                if (e.shiftKey) {
                                    tabLeft()
                                } else {
                                    tabRight()
                                }
                            }

                            if (e.key === 'Enter') {
                                e.preventDefault()
                                selectSelected()
                            }
                            if (e.key === 'Escape') {
                                e.preventDefault()
                                onClose?.()
                            }
                        }}
                        ref={searchInputRef}
                        onChange={(newValue) => setSearchQuery(newValue)}
                    />
                </div>
                <InfiniteSelectResults focusInput={focusInput} taxonomicFilterLogicProps={taxonomicFilterLogicProps} />
            </div>
        </BindLogic>
    )
}
