import { Notebook } from 'scenes/notebooks/Notebook/Notebook'
import { NotebookMode, NotebookType } from '~/types'

export function ExportedNotebook(props: { notebook: NotebookType }): JSX.Element {
    return (
        <div className={'ExportedNotebook Notebook--compact pt-4 px-8 mb-8'}>
            <Notebook
                shortId={props.notebook.short_id}
                cachedNotebook={props.notebook}
                editable={false}
                viewMode={NotebookMode.SharedView}
            />
        </div>
    )
}
