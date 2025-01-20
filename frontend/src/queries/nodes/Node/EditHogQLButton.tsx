import { LemonButton, LemonButtonWithoutSideActionProps } from '@posthog/lemon-ui'
import { IconQueryEditor } from 'lib/lemon-ui/icons'
import { urls } from 'scenes/urls'

import { DataTableNode, NodeKind } from '~/queries/schema/schema-general'

export interface EditHogQLButtonProps extends LemonButtonWithoutSideActionProps {
    hogql: string
}

export function EditHogQLButton({ hogql, ...props }: EditHogQLButtonProps): JSX.Element {
    const query: DataTableNode = {
        kind: NodeKind.DataTableNode,
        full: true,
        source: { kind: NodeKind.HogQLQuery, query: hogql },
    }
    return (
        <LemonButton
            data-attr="open-json-editor-button"
            type="secondary"
            to={urls.insightNew(undefined, undefined, query)}
            icon={<IconQueryEditor />}
            tooltip="Edit SQL directly"
            {...props}
        />
    )
}
