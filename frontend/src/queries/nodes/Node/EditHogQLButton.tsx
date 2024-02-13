import { IconQueryEditor } from 'lib/lemon-ui/icons'
import { LemonButton, LemonButtonWithoutSideActionProps } from 'lib/lemon-ui/LemonButton'
import { urls } from 'scenes/urls'

import { NodeKind } from '~/queries/schema'

export interface EditHogQLButtonProps extends LemonButtonWithoutSideActionProps {
    hogql: string
}

export function EditHogQLButton({ hogql, ...props }: EditHogQLButtonProps): JSX.Element {
    return (
        <LemonButton
            data-attr="open-json-editor-button"
            type="secondary"
            to={urls.insightNew(
                undefined,
                undefined,
                JSON.stringify({
                    kind: NodeKind.DataTableNode,
                    full: true,
                    source: { kind: NodeKind.HogQLQuery, query: hogql },
                })
            )}
            icon={<IconQueryEditor />}
            tooltip="Edit SQL directly"
            {...props}
        />
    )
}
