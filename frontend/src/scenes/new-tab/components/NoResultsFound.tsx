import { useActions } from 'kea'

import { IconInfo } from '@posthog/icons'

import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { ListBox } from 'lib/ui/ListBox/ListBox'

import { newTabSceneLogic } from '../newTabSceneLogic'

export function NoResultsFound({ handleAskAi }: { handleAskAi: () => void }): JSX.Element {
    const { setSearch } = useActions(newTabSceneLogic)
    return (
        <div className="flex flex-col gap-4 px-2 py-2 bg-glass-bg-3000 rounded-lg">
            <div className="flex flex-col gap-1">
                <p className="text-tertiary mb-2">
                    <IconInfo /> No results found
                </p>
                <div className="flex gap-1">
                    <ListBox.Item asChild className="list-none">
                        <ButtonPrimitive size="sm" onClick={() => setSearch('')} variant="panel">
                            Clear search
                        </ButtonPrimitive>{' '}
                    </ListBox.Item>
                    or{' '}
                    <ListBox.Item asChild>
                        <ButtonPrimitive size="sm" onClick={() => handleAskAi()} variant="panel">
                            Ask Posthog AI
                        </ButtonPrimitive>
                    </ListBox.Item>
                </div>
            </div>
        </div>
    )
}
