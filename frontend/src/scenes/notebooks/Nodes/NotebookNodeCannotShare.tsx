import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { BuilderHog3 } from 'lib/components/hedgehogs'
import { NotebookNodeType } from '~/types'

const nodeTypeDescription: Record<NotebookNodeType, string> = {
    [NotebookNodeType.Insight]: 'insights',
    [NotebookNodeType.Query]: 'queries',
    [NotebookNodeType.Recording]: 'recordings',
    [NotebookNodeType.RecordingPlaylist]: 'playlists',
    [NotebookNodeType.FeatureFlag]: 'flags',
    [NotebookNodeType.Person]: 'persons',
    [NotebookNodeType.Link]: 'links',
}

export function NotebookNodeCannotShare({ type }: { type: NotebookNodeType }): JSX.Element {
    return (
        <div
            className={
                'flex py-4 px-8 w-full flex-col justify-center items-center border-2 rounded bg-primary-alt-highlight'
            }
        >
            <div className={'flex flex-row items-center justify-center'}>
                <BuilderHog3 width={75} height={75} />
                <LemonTag type={'highlight'}>Coming soon</LemonTag>
            </div>
            <h2>Shared Notebooks cannot display {nodeTypeDescription[type]} (yet!).</h2>
        </div>
    )
}
