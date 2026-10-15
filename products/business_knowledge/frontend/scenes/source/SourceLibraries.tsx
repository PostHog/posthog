import { useActions, useValues } from 'kea'

import { LemonInputSelect } from '@posthog/lemon-ui'

import { knowledgeSourceLogic } from './knowledgeSourceLogic'

export function SourceLibraries(): JSX.Element {
    const { source, libraries, savingLibraries } = useValues(knowledgeSourceLogic)
    const { saveSourceLibraries } = useActions(knowledgeSourceLogic)
    const selected = [...(source?.library_ids ?? [])]
    return (
        <div className="flex flex-col gap-1">
            <span className="text-muted-alt">Libraries</span>
            <LemonInputSelect
                mode="multiple"
                value={selected}
                options={libraries.map((library) => ({ key: library.id, label: library.name }))}
                onChange={(libraryIds) => {
                    if (savingLibraries) {
                        return
                    }
                    saveSourceLibraries(libraryIds)
                }}
                loading={savingLibraries}
                placeholder="No library"
            />
        </div>
    )
}
