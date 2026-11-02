import { useActions, useValues } from 'kea'

import { IconPlus } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { llmEvaluationsLogic } from '../llmEvaluationsLogic'
import { EvaluationDirectoryTile } from './EvaluationDirectoryTile'
import { evaluationsOverviewLogic } from './evaluationsOverviewLogic'

/** Directories as compact tiles, like a file browser, so a long list of them still fits in a couple of rows. */
export function EvaluationDirectoryTiles(): JSX.Element | null {
    const { directoryTiles, selectedDirectoryId } = useValues(evaluationsOverviewLogic)
    const { openCreateDirectory } = useActions(llmEvaluationsLogic)
    const editorReason = getAccessControlDisabledReason(AccessControlResourceType.Evaluation, AccessControlLevel.Editor)

    // Few teams use directories, so the tiles only appear once a team has made one.
    if (directoryTiles.length === 0) {
        return null
    }
    return (
        <div className="@container">
            <div className="grid gap-2 grid-cols-1 @min-[30rem]:grid-cols-2 @3xl:grid-cols-3 @5xl:grid-cols-4 @7xl:grid-cols-6">
                {directoryTiles.map((tile) => (
                    <EvaluationDirectoryTile
                        key={tile.directory.id}
                        tile={tile}
                        selected={tile.directory.id === selectedDirectoryId}
                    />
                ))}
                <Tooltip title={editorReason}>
                    <button
                        type="button"
                        onClick={() => openCreateDirectory()}
                        disabled={!!editorReason}
                        className="flex items-center gap-3 rounded-lg border-2 border-dotted border-secondary px-3 py-2 text-left text-secondary enabled:hover:text-primary enabled:hover:border-accent enabled:cursor-pointer disabled:opacity-60"
                        data-attr="create-evaluation-directory-button"
                    >
                        <span className="flex size-8 shrink-0 items-center justify-center rounded text-lg">
                            <IconPlus />
                        </span>
                        <span className="font-semibold">New directory</span>
                    </button>
                </Tooltip>
            </div>
        </div>
    )
}
