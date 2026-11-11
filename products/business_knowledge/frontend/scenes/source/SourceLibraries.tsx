import { LemonInputSelect } from '@posthog/lemon-ui'

import type { KnowledgeLibrary } from '../../api'

export function SourceLibraries({
    libraries,
    selectedIds,
    saving,
    onChange,
}: {
    libraries: KnowledgeLibrary[]
    selectedIds: readonly string[]
    saving: boolean
    onChange: (libraryIds: string[]) => void
}): JSX.Element {
    return (
        <div className="flex flex-col gap-1">
            <span className="text-muted-alt">Libraries</span>
            <LemonInputSelect
                mode="multiple"
                value={[...selectedIds]}
                options={libraries.map((library) => ({ key: library.id, label: library.name }))}
                onChange={(libraryIds) => {
                    if (saving) {
                        return
                    }
                    onChange(libraryIds)
                }}
                loading={saving}
                placeholder="No library"
            />
        </div>
    )
}
