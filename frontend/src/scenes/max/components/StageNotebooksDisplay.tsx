import { IconCheck, IconNotebook } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { NotebookTarget } from 'scenes/notebooks/types'

import { openNotebook } from '~/models/notebooksModel'
import { DeepResearchNotebookInfo } from '~/types'

interface StageNotebooksDisplayProps {
    stageNotebooks: DeepResearchNotebookInfo[]
}

const STAGE_DISPLAY_NAMES: Record<string, string> = {
    planning: 'Planning',
    notebook_planning: 'Planning',
    report: 'Final Report',
}

const STAGE_DESCRIPTIONS: Record<string, string> = {
    planning: 'Initial research plan and objectives',
    notebook_planning: 'Initial research plan and objectives',
    report: 'Comprehensive analysis and findings',
}

export function StageNotebooksDisplay({ stageNotebooks }: StageNotebooksDisplayProps): JSX.Element {
    const handleOpenNotebook = (notebookId: string): void => {
        openNotebook(notebookId, NotebookTarget.Scene)
    }

    if (!stageNotebooks.length) {
        return <></>
    }

    return (
        <div className="bg-bg-light border border-border rounded-lg p-4 space-y-3">
            <div className="flex items-center gap-2">
                <IconCheck className="text-success size-4" />
                <h4 className="text-sm font-semibold m-0">Deep Research Complete</h4>
            </div>

            <div className="space-y-2">
                <p className="text-xs text-muted mb-3">
                    Your research has been completed across multiple stages. Each notebook contains detailed analysis:
                </p>

                {stageNotebooks.map((notebook) => {
                    const displayName = STAGE_DISPLAY_NAMES[notebook.stage] || notebook.stage
                    const description = STAGE_DESCRIPTIONS[notebook.stage] || 'Research documentation'

                    return (
                        <div
                            key={notebook.notebook_id}
                            className="flex items-center justify-between p-3 bg-bg-3000 rounded border border-border-light"
                        >
                            <div className="flex items-start gap-3">
                                <IconNotebook className="size-4 text-primary-alt mt-0.5" />
                                <div>
                                    <div className="font-medium text-sm">
                                        {notebook.title || `${displayName} Notebook`}
                                    </div>
                                    <div className="text-xs text-muted">{description}</div>
                                </div>
                            </div>
                            <LemonButton
                                onClick={() => handleOpenNotebook(notebook.notebook_id)}
                                size="xsmall"
                                type="primary"
                                icon={<IconOpenInNew />}
                            >
                                Open
                            </LemonButton>
                        </div>
                    )
                })}
            </div>
        </div>
    )
}
