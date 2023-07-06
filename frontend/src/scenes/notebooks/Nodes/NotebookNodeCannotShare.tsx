import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'

export function NotebookNodeCannotShare({
    type,
}: {
    type: 'flags' | 'insights' | 'persons' | 'playlists' | 'queries' | 'recordings'
}): JSX.Element {
    return (
        <h2 className={'flex py-4 px-8 w-full items-center justify-center border rounded'}>
            Shared Notebooks cannot display {type} (yet!). <LemonTag type={'warning'}>Coming soon</LemonTag>
        </h2>
    )
}
