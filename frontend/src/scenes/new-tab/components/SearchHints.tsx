import { IconSidePanel } from '@posthog/icons'

import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { ListBox } from 'lib/ui/ListBox/ListBox'

import { SidePanelTab } from '~/types'

import { SpecialSearchMode } from '../newTabSceneLogic'

interface SearchHintsProps {
    specialSearchMode: SpecialSearchMode
    search: string
    filteredItemsGridLength: number
    setSearch: (search: string) => void
    setQuestion: (question: string) => void
    focusMaxInput: () => void
    focusSearchInput: () => void
    openSidePanel: (tab: SidePanelTab) => void
}

export function SearchHints({
    specialSearchMode,
    search,
    filteredItemsGridLength,
    setSearch,
    setQuestion,
    focusMaxInput,
    focusSearchInput,
    openSidePanel,
}: SearchHintsProps): JSX.Element {
    return (
        <div className="flex justify-between items-center relative text-xs font-medium overflow-hidden py-1 px-1.5 border-x border-b rounded-b backdrop-blur-sm bg-[var(--glass-bg-3000)]">
            {specialSearchMode === 'person' && search.trim() ? (
                <span>
                    <span className="text-tertiary mr-1">Try searching persons by:</span>
                    <ListBox.Item asChild>
                        <ButtonPrimitive
                            size="xxs"
                            className="text-xs -ml-1"
                            onClick={() => {
                                setSearch('/persons test@email.com')
                                focusSearchInput()
                            }}
                        >
                            email
                        </ButtonPrimitive>
                    </ListBox.Item>
                    <span className="text-tertiary">or</span>
                    <ListBox.Item asChild>
                        <ButtonPrimitive
                            size="xxs"
                            className="text-xs"
                            onClick={() => {
                                setSearch('/persons some-id')
                                focusSearchInput()
                            }}
                        >
                            ID
                        </ButtonPrimitive>
                    </ListBox.Item>
                </span>
            ) : (
                <span>
                    <span className="text-tertiary">Try:</span>
                    <ListBox.Item asChild>
                        <ButtonPrimitive
                            size="xxs"
                            className="text-xs"
                            onClick={() => {
                                setSearch('/persons ')
                                focusSearchInput()
                            }}
                        >
                            /persons <span className="text-tertiary -ml-1">$email/id</span>
                        </ButtonPrimitive>
                    </ListBox.Item>
                    <span className="text-tertiary">or</span>
                    <ListBox.Item asChild>
                        <ButtonPrimitive
                            size="xxs"
                            className="text-xs"
                            onClick={() => {
                                setSearch('Experiment')
                                focusSearchInput()
                            }}
                        >
                            Experiment
                        </ButtonPrimitive>
                    </ListBox.Item>
                </span>
            )}
            <span className="text-primary flex gap-1 items-center">
                {/* if filtered results length is 0, this will be the first to focus */}
                <ListBox.Item asChild focusFirst={filteredItemsGridLength === 0}>
                    <ButtonPrimitive
                        size="xxs"
                        onClick={() => {
                            openSidePanel(SidePanelTab.Max)
                            setSearch('')
                            setQuestion(search)
                            focusMaxInput()
                        }}
                        className="text-xs"
                        tooltip="Hit enter to open Max!"
                    >
                        Ask Max!
                        <IconSidePanel />
                    </ButtonPrimitive>
                </ListBox.Item>
            </span>
        </div>
    )
}
