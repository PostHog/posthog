import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Node } from '~/queries/schema'
import { urls } from 'scenes/urls'
import { IconEvent } from 'lib/lemon-ui/icons'

export interface InlineEditorButtonProps {
    query: Node
}

export function OpenEditorButton({ query }: InlineEditorButtonProps): JSX.Element {
    return (
        <>
            <LemonButton
                type="secondary"
                to={urls.insightNew(undefined, undefined, JSON.stringify(query))}
                icon={<IconEvent />}
                title={'Open in query editor'}
            />
        </>
    )
}
