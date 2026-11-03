import { useActions, useValues } from 'kea'

import { IconDocument, IconFolder, IconFolderOpen, IconGithub, IconPencil, IconTrash } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonTag } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { pluralize } from 'lib/utils/strings'

import { LIBRARY_SCOPE_ALL, LIBRARY_SCOPE_UNFILED, businessKnowledgeLogic } from './businessKnowledgeLogic'
import { LibrarySummaryPanel } from './LibrarySummaryPanel'

export function LibrarySummary(): JSX.Element | null {
    const { libraryScope, selectedLibrary, libraries, librariesLoading, savingLibrary } =
        useValues(businessKnowledgeLogic)
    const { openLibraryDialog, deleteSelectedLibrary } = useActions(businessKnowledgeLogic)

    if (libraryScope === LIBRARY_SCOPE_UNFILED) {
        return (
            <LibrarySummaryPanel icon={<IconDocument />} title="No library">
                <p className="m-0 text-sm text-secondary">
                    Sources that are not in any library. Open a source to add it to a library.
                </p>
            </LibrarySummaryPanel>
        )
    }

    if (libraryScope === LIBRARY_SCOPE_ALL) {
        if (librariesLoading || libraries.length > 0) {
            return null
        }
        return (
            <LibrarySummaryPanel icon={<IconFolder />} title="Libraries">
                <p className="m-0 text-sm text-secondary">
                    Group sources into libraries to keep them organized. API and MCP search can then look in one library
                    instead of every source.
                </p>
            </LibrarySummaryPanel>
        )
    }

    if (!selectedLibrary) {
        return null
    }

    const counts = [
        pluralize(selectedLibrary.source_count, 'source'),
        pluralize(selectedLibrary.repos.length, 'repository', 'repositories'),
    ]

    return (
        <LibrarySummaryPanel
            icon={<IconFolderOpen />}
            title={selectedLibrary.name}
            tag={selectedLibrary.is_default ? <LemonTag type="highlight">Default</LemonTag> : null}
            actions={
                <>
                    <LemonButton
                        size="small"
                        type="secondary"
                        icon={<IconPencil />}
                        onClick={() => openLibraryDialog('rename')}
                        data-attr="business-knowledge-library-rename"
                    >
                        Rename
                    </LemonButton>
                    <LemonButton
                        size="small"
                        type="secondary"
                        icon={<IconGithub />}
                        onClick={() => openLibraryDialog('repos')}
                        data-attr="business-knowledge-library-repos"
                    >
                        Repositories
                    </LemonButton>
                    <LemonButton
                        size="small"
                        type="secondary"
                        status="danger"
                        icon={<IconTrash />}
                        disabledReason={savingLibrary ? 'Saving' : undefined}
                        data-attr="business-knowledge-library-delete"
                        onClick={() =>
                            LemonDialog.open({
                                title: `Delete "${selectedLibrary.name}"?`,
                                description: 'Sources and repositories stay. Only this library is removed.',
                                primaryButton: {
                                    children: 'Delete library',
                                    status: 'danger',
                                    onClick: () => deleteSelectedLibrary(),
                                },
                                secondaryButton: { children: 'Cancel' },
                            })
                        }
                    >
                        Delete
                    </LemonButton>
                </>
            }
        >
            <p className="m-0 text-sm text-secondary">
                <span translate="no">{counts.join(' · ')}</span>
                {selectedLibrary.is_default && <span>. Sources learned from support tickets join this library.</span>}
            </p>
            {selectedLibrary.repos.length > 0 && (
                <div className="flex flex-wrap gap-1">
                    {selectedLibrary.repos.map((repo) => (
                        <LemonTag key={repo} icon={<IconGithub />}>
                            {repo}
                        </LemonTag>
                    ))}
                </div>
            )}
            <div className="flex flex-wrap items-center gap-1 text-xs text-secondary">
                <span>ID for API and MCP search:</span>
                <CopyToClipboardInline explicitValue={selectedLibrary.id} description="library ID" selectable>
                    {selectedLibrary.id}
                </CopyToClipboardInline>
            </div>
        </LibrarySummaryPanel>
    )
}
