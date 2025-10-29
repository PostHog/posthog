import { useActions, useValues } from 'kea'

import { IconSparkles } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { ListBox } from 'lib/ui/ListBox/ListBox'

import { newTabSceneLogic } from '../newTabSceneLogic'

interface SearchHintsProps {
    filteredItemsGridLength: number
    focusSearchInput: () => void
    tabId: string
    handleAskAi: (question?: string) => void
}

export function SearchHints({ focusSearchInput, tabId, handleAskAi }: SearchHintsProps): JSX.Element {
    const newTabSceneData = useFeatureFlag('DATA_IN_NEW_TAB_SCENE')
    const { setSearch } = useActions(newTabSceneLogic({ tabId }))
    const { search } = useValues(newTabSceneLogic({ tabId }))
    return (
        <div className="flex justify-between items-center relative text-xs font-medium overflow-hidden py-1 px-1.5 border-x border-b rounded-b backdrop-blur-sm bg-[var(--glass-bg-3000)]">
            <span>
                <span className="text-tertiary">Try:</span>
                <ListBox.Item asChild>
                    <ButtonPrimitive
                        size="xxs"
                        className="text-xs"
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

            {!newTabSceneData && (
                <span className="text-primary flex gap-1 items-center">
                    <ListBox.Item asChild>
                        <ButtonPrimitive
                            size="xxs"
                            onClick={() => handleAskAi(search)}
                            className="text-xs"
                            tooltip="Hit enter to open Posthog AI"
                        >
                            <IconSparkles className="size-4" />
                            Ask Posthog AI
                        </ButtonPrimitive>
                    </ListBox.Item>
                </span>
            )}
        </div>
    )
}
