import { Notebook } from 'scenes/notebooks/Notebook/Notebook'

interface GroupNotebookCardProps {
    shortId: string
}

export function GroupNotebookCard({ shortId }: GroupNotebookCardProps): JSX.Element {
    return (
        <div className="flex-1 bg-white rounded-lg px-4">
            <Notebook shortId={shortId} editable={true} initialAutofocus="end" />
        </div>
    )
}
