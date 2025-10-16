import { IconSidePanel } from '@posthog/icons'

import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { ListBox } from 'lib/ui/ListBox/ListBox'

import { SidePanelTab } from '~/types'

interface SearchHintsProps {
    search: string
    filteredItemsGridLength: number
    setSearch: (search: string) => void
    setQuestion: (question: string) => void
    focusMaxInput: () => void
    focusSearchInput: () => void
    openSidePanel: (tab: SidePanelTab) => void
}

export function SearchHints({
    search,
    setSearch,
    setQuestion,
    focusMaxInput,
    focusSearchInput,
    openSidePanel,
}: SearchHintsProps): JSX.Element {
    return (
        <div className="flex justify-between items-center relative text-xs font-medium overflow-hidden py-1 px-1.5 border-x border-b rounded-b backdrop-blur-sm bg-[var(--glass-bg-3000)]">
            <span>
                <span className="text-tertiary">Try:</span>
                <ListBox.Item asChild>
                    <ButtonPrimitive
                        size="xxs"
                        className="text-xs data-[focused=true]:outline-2 data-[focused=true]:outline-accent"
                        onClick={() => {
                            setSearch('New SQL query')
                            focusSearchInput()
                        }}
                    >
                        New SQL query
                    </ButtonPrimitive>
                </ListBox.Item>
                <span className="text-tertiary">or</span>
                <ListBox.Item asChild>
                    <ButtonPrimitive
                        size="xxs"
                        className="text-xs data-[focused=true]:outline-2 data-[focused=true]:outline-accent"
                        onClick={() => {
                            setSearch('Experiment')
                            focusSearchInput()
                        }}
                    >
                        Experiment
                    </ButtonPrimitive>
                </ListBox.Item>
            </span>

            <span className="text-primary flex gap-1 items-center">
                <ListBox.Item asChild>
                    <ButtonPrimitive
                        size="xxs"
                        onClick={() => {
                            openSidePanel(SidePanelTab.Max)
                            setSearch('')
                            setQuestion(search)
                            focusMaxInput()
                        }}
                        className="text-xs data-[focused=true]:outline-2 data-[focused=true]:outline-accent"
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
