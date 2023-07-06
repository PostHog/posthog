import { Notebook } from 'scenes/notebooks/Notebook/Notebook'
import { NotebookType } from '~/types'

export function ExportedNotebook(props: { notebook: NotebookType }): JSX.Element {
    return (
        <div className={'ExportedNotebook pt-4 px-8 mb-8'}>
            <Notebook shortId={props.notebook.short_id} cachedNotebook={props.notebook} editable={false} />
        </div>
    )
}
