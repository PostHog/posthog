import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Notebook } from 'scenes/notebooks/Notebook/Notebook'
import { urls } from 'scenes/urls'

export function GroupNotebookCard(): JSX.Element {
    // TODO: hardcoded as scratchpad temporarily until the backend relationship between groups and notebooks is created
    const shortId = 'scratchpad'
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
