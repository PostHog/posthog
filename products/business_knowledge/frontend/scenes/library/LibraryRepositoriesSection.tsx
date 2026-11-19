import { useActions, useValues } from 'kea'

import { IconGithub, IconPencil } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { knowledgeLibraryLogic } from './knowledgeLibraryLogic'

export function LibraryRepositoriesSection(): JSX.Element | null {
    const { library } = useValues(knowledgeLibraryLogic)
    const { openDialog } = useActions(knowledgeLibraryLogic)

    if (!library) {
        return null
    }

    return (
        <SceneSection
            title="Repositories"
            description="An agent with a key for this library reads only these GitHub repositories."
            className="gap-y-2"
        >
            <div className="flex flex-wrap items-center gap-1">
                {library.repos.length === 0 ? (
                    <span className="text-secondary">No repositories in this library.</span>
                ) : (
                    library.repos.map((repo) => (
                        <LemonTag key={repo} icon={<IconGithub />}>
                            {repo}
                        </LemonTag>
                    ))
                )}
                <LemonButton
                    size="small"
                    type="secondary"
                    icon={<IconPencil />}
                    onClick={() => openDialog('repos')}
                    // pinned: autocapture key. Do not rename.
                    data-attr="business-knowledge-library-repos"
                >
                    Edit repositories
                </LemonButton>
            </div>
        </SceneSection>
    )
}
