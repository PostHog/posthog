import { IconPreview } from 'lib/lemon-ui/icons'
import { LemonButton, LemonButtonWithoutSideActionProps } from 'lib/lemon-ui/LemonButton'
import { urls } from 'scenes/urls'

import { Node } from '~/queries/schema'

export interface OpenEditorButtonProps extends LemonButtonWithoutSideActionProps {
    query: Node | null
}

export function OpenEditorButton({ query, ...props }: OpenEditorButtonProps): JSX.Element {
    return (
        <LemonButton
            data-attr="open-json-editor-button"
            type="secondary"
            to={query ? urls.insightNew(undefined, undefined, query) : undefined}
            icon={<IconPreview />}
            tooltip="Open as a new insight"
            {...props}
        />
    )
}
