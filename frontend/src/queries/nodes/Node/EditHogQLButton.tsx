import { LemonButton, LemonButtonWithoutSideActionProps } from 'lib/lemon-ui/LemonButton'
import { IconQueryEditor } from 'lib/lemon-ui/icons'
import { urls } from 'scenes/urls'

export interface EditHogQLButtonProps extends LemonButtonWithoutSideActionProps {
    hogql: string
}

export function EditHogQLButton({ hogql, ...props }: EditHogQLButtonProps): JSX.Element {
    return (
        <LemonButton
            data-attr="open-json-editor-button"
            type="secondary"
            to={urls.sqlEditor(hogql)}
            icon={<IconQueryEditor />}
            tooltip="Edit SQL directly"
            {...props}
        />
    )
}
