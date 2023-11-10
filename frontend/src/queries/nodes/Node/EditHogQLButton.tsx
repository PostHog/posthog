import { LemonButton, LemonButtonProps } from 'lib/lemon-ui/LemonButton'
import { NodeKind } from '~/queries/schema'
import { urls } from 'scenes/urls'
import { IconQueryEditor } from 'lib/lemon-ui/icons'

export interface EditHogQLButtonProps extends LemonButtonProps {
    hogql: string
}

export function EditHogQLButton({ hogql, ...props }: EditHogQLButtonProps): JSX.Element {
    return (
        <LemonButton
            data-attr={'open-json-editor-button'}
            type="secondary"
            status="primary-alt"
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
            tooltip={'Edit SQL directly'}
            {...props}
        />
    )
}
