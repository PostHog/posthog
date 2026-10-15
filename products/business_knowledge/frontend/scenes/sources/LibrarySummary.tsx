import { useActions, useValues } from 'kea'

import { IconDocument, IconFolder, IconFolderOpen, IconGithub, IconPencil, IconTrash } from '@posthog/icons'
import { LemonButton, LemonCard, LemonDialog, LemonTag } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { pluralize } from 'lib/utils/strings'

import { LIBRARY_SCOPE_ALL, LIBRARY_SCOPE_UNFILED, businessKnowledgeLogic } from './businessKnowledgeLogic'

export function LibrarySummary(): JSX.Element | null {
    const githubEnabled = useFeatureFlag('BUSINESS_KNOWLEDGE_GITHUB_REPOS')
    const { libraryScope, selectedLibrary, libraries, librariesLoading, savingLibrary } =
        useValues(businessKnowledgeLogic)
    const { openLibraryDialog, deleteSelectedLibrary } = useActions(businessKnowledgeLogic)

    if (libraryScope === LIBRARY_SCOPE_UNFILED) {
        return (
            <SummaryPanel icon={<IconDocument />} title="No library">
                <p className="m-0 text-sm text-secondary">
                    Sources that are not in any library. Open a source to add it to a library.
                </p>
            </SummaryPanel>
        )
    }

    if (libraryScope === LIBRARY_SCOPE_ALL) {
        if (librariesLoading || libraries.length > 0) {
            return null
        }
        return (
            <SummaryPanel icon={<IconFolder />} title="Libraries">
                <p className="m-0 text-sm text-secondary">
                    Group sources into libraries to keep them organized. API and MCP search can then look in one library
                    instead of every source.
                </p>
            </SummaryPanel>
        )
    }

    if (!selectedLibrary) {
        return null
    }

    const counts = [pluralize(selectedLibrary.source_count, 'source')]
    if (githubEnabled) {
        counts.push(pluralize(selectedLibrary.repos.length, 'repository', 'repositories'))
    }

    return (
        <SummaryPanel
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
                    {githubEnabled && (
                        <LemonButton
                            size="small"
                            type="secondary"
                            icon={<IconGithub />}
                            onClick={() => openLibraryDialog('repos')}
                            data-attr="business-knowledge-library-repos"
                        >
                            Repositories
                        </LemonButton>
                    )}
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
            {githubEnabled && selectedLibrary.repos.length > 0 && (
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
        </SummaryPanel>
    )
}

function SummaryPanel({
    icon,
    title,
    tag,
    actions,
    children,
}: {
    icon: JSX.Element
    title: string
    tag?: JSX.Element | null
    actions?: JSX.Element
    children: React.ReactNode
}): JSX.Element {
    return (
        <LemonCard hoverEffect={false} className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2 p-3">
            <div className="flex min-w-0 flex-1 flex-col gap-1">
                <div className="flex min-w-0 items-center gap-2">
                    <span className="flex shrink-0 text-lg text-secondary">{icon}</span>
                    <h3 className="m-0 truncate text-base font-semibold">{title}</h3>
                    {tag}
                </div>
                {children}
            </div>
            {actions && <div className="flex shrink-0 flex-wrap gap-1">{actions}</div>}
        </LemonCard>
    )
}
