import './TaxonomicFilter.scss'
import React, { useEffect, useMemo, useRef } from 'react'
import { Input } from 'antd'
import { useValues, useActions, BindLogic } from 'kea'
import { InfiniteSelectResults } from './InfiniteSelectResults'
import { taxonomicFilterLogic } from './taxonomicFilterLogic'
import { TaxonomicFilterLogicProps, TaxonomicFilterProps } from 'lib/components/TaxonomicFilter/types'
import { IconKeyboard, IconMagnifier } from '../icons'
import { Tooltip } from '../Tooltip'
import { DefinitionPanel } from 'lib/components/DefinitionPanel/DefinitionPanel'

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
}: TaxonomicFilterProps): JSX.Element {
    // Generate a unique key for each unique TaxonomicFilter that's rendered
    const taxonomicFilterLogicKey = useMemo(
        () => taxonomicFilterLogicKeyInput || `taxonomic-filter-${uniqueMemoizedIndex++}`,
        [taxonomicFilterLogicKeyInput]
    )

    const searchInputRef = useRef<Input | null>(null)
    const focusInput = (): void => searchInputRef.current?.focus()

    const taxonomicFilterLogicProps: TaxonomicFilterLogicProps = {
        taxonomicFilterLogicKey,
        groupType,
        value,
        onChange,
        taxonomicGroupTypes,
        optionsFromProp,
        eventNames,
    }
    const logic = taxonomicFilterLogic(taxonomicFilterLogicProps)
    const { searchQuery, searchPlaceholder } = useValues(logic)
    const { setSearchQuery, moveUp, moveDown, tabLeft, tabRight, selectSelected } = useActions(logic)

    useEffect(() => {
        window.setTimeout(() => focusInput(), 1)
    }, [])

    return (
        <>
            <BindLogic logic={taxonomicFilterLogic} props={taxonomicFilterLogicProps}>
                <div className={`taxonomic-filter${taxonomicGroupTypes.length === 1 ? ' one-taxonomic-tab' : ''}`}>
                    <div style={{ position: 'relative' }}>
                        <Input
                            style={{ flexGrow: 1 }}
                            data-attr="taxonomic-filter-searchfield"
                            placeholder={`Search ${searchPlaceholder}`}
                            prefix={
                                <IconMagnifier
                                    className={`magnifier-icon${searchQuery ? ' magnifier-icon-active' : ''}`}
                                />
                            }
                            value={searchQuery}
                            ref={(ref) => (searchInputRef.current = ref)}
                            onChange={(e) => setSearchQuery(e.target.value)}
                            onKeyDown={(e) => {
                                if (e.key === 'ArrowUp') {
                                    e.preventDefault()
                                    moveUp()
                                }
                                if (e.key === 'ArrowDown') {
                                    e.preventDefault()
                                    moveDown()
                                }
                                if (e.key === 'ArrowLeft') {
                                    e.preventDefault()
                                    tabLeft()
                                }
                                if (e.key === 'ArrowRight') {
                                    e.preventDefault()
                                    tabRight()
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
                        />
                        <span
                            className="text-muted-alt cursor-pointer"
                            style={{ paddingLeft: 4, fontSize: '1.2em', position: 'absolute', right: 7, top: 5 }}
                        >
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
                                <IconKeyboard />
                            </Tooltip>
                        </span>
                    </div>
                    <InfiniteSelectResults
                        focusInput={focusInput}
                        taxonomicFilterLogicProps={taxonomicFilterLogicProps}
                    />
                </div>
            </BindLogic>
            <DefinitionPanel />
        </>
    )
}
