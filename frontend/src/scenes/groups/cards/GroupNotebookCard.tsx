import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Notebook } from 'scenes/notebooks/Notebook/Notebook'
import { urls } from 'scenes/urls'

interface GroupNotebookCardProps {
    shortId: string
}

export function GroupNotebookCard({ shortId }: GroupNotebookCardProps): JSX.Element {
    return (
        <div className="flex flex-col gap-2 h-full min-h-80">
            <div className="flex-1 relative">
                <div className="absolute inset-0 overflow-y-auto">
                    <Notebook shortId={shortId} editable={true} initialAutofocus="end" />
                </div>
            </div>
            <div className="flex justify-end">
                <LemonButton type="secondary" size="small" to={urls.notebook(shortId)}>
                    Open notebook
                </LemonButton>
            </div>
        </div>
    )
}
