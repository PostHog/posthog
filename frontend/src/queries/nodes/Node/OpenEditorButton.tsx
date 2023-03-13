import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Node } from '~/queries/schema'
import { urls } from 'scenes/urls'
import { IconQueryEditor } from 'lib/lemon-ui/icons'

export interface InlineEditorButtonProps {
    query: Node
}

export function OpenEditorButton({ query }: InlineEditorButtonProps): JSX.Element {
    return (
        <>
            <LemonButton
                type="secondary"
                status="primary-alt"
                to={urls.insightNew(undefined, undefined, JSON.stringify(query))}
                icon={<IconQueryEditor />}
                title={'Open in query editor'}
            />
        </>
    )
}
