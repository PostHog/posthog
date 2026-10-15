import { useActions, useValues } from 'kea'

import { IconDocument, IconFolder, IconFolderOpen, IconPlusSmall, IconStack } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonMenu } from '@posthog/lemon-ui'

import { LIBRARY_SCOPE_ALL, LIBRARY_SCOPE_UNFILED, businessKnowledgeLogic } from './businessKnowledgeLogic'
import { LibraryButton } from './LibraryButton'

const VISIBLE_LIBRARIES = 8

export function LibraryRow(): JSX.Element {
    const { libraries, libraryScope, selectedLibrary } = useValues(businessKnowledgeLogic)
    const { setLibraryScope, openLibraryDialog } = useActions(businessKnowledgeLogic)
    const visible = libraries.slice(0, VISIBLE_LIBRARIES)
    const overflow = libraries.slice(VISIBLE_LIBRARIES)
    const overflowSelected = overflow.some((library) => library.id === libraryScope)

    return (
        <div className="flex flex-wrap items-center gap-1" data-attr="business-knowledge-library-row">
            <LemonButton
                size="small"
                icon={<IconStack />}
                active={libraryScope === LIBRARY_SCOPE_ALL}
                onClick={() => setLibraryScope(LIBRARY_SCOPE_ALL)}
                data-attr="business-knowledge-library-all"
            >
                All
            </LemonButton>
            {libraries.length > 0 && <LemonDivider vertical className="h-5 mx-1" />}
            {visible.map((library) => (
                <LibraryButton
                    key={library.id}
                    library={library}
                    active={libraryScope === library.id}
                    onClick={() => setLibraryScope(library.id)}
                />
            ))}
            {overflow.length > 0 && (
                <LemonMenu
                    items={overflow.map((library) => ({
                        label: `${library.name} (${library.source_count})`,
                        active: libraryScope === library.id,
                        onClick: () => setLibraryScope(library.id),
                    }))}
                >
                    <LemonButton
                        size="small"
                        icon={overflowSelected ? <IconFolderOpen /> : <IconFolder />}
                        active={overflowSelected}
                    >
                        <span className="max-w-40 truncate">
                            {overflowSelected && selectedLibrary ? selectedLibrary.name : `${overflow.length} more`}
                        </span>
                    </LemonButton>
                </LemonMenu>
            )}
            {libraries.length > 0 && (
                <LemonButton
                    size="small"
                    icon={<IconDocument />}
                    active={libraryScope === LIBRARY_SCOPE_UNFILED}
                    onClick={() => setLibraryScope(LIBRARY_SCOPE_UNFILED)}
                    tooltip="Sources that are not in any library"
                    data-attr="business-knowledge-library-unfiled"
                >
                    No library
                </LemonButton>
            )}
            <LemonButton
                size="small"
                type="tertiary"
                icon={<IconPlusSmall />}
                onClick={() => openLibraryDialog('create')}
                data-attr="business-knowledge-library-new"
            >
                New library
            </LemonButton>
        </div>
    )
}
