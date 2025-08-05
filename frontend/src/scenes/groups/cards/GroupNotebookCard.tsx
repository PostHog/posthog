import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Notebook } from 'scenes/notebooks/Notebook/Notebook'
import { urls } from 'scenes/urls'

interface GroupNotebookCardProps {
    shortId: string
}

export function GroupNotebookCard({ shortId }: GroupNotebookCardProps): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            <div className="flex justify-end">
                <LemonButton type="secondary" size="small" to={urls.notebook(shortId)}>
                    Open notebook
                </LemonButton>
            </div>
            <div className="flex-1">
                <Notebook shortId={shortId} editable={true} initialAutofocus="end" />
            </div>
        </div>
    )
}
