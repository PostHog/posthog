import { LemonButton, LemonButtonWithSideActionProps } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { IconNotebook } from 'scenes/notebooks/IconNotebook'
import { notebookPanelLogic } from 'scenes/notebooks/NotebookPanel/notebookPanelLogic'

export function NotebookButton(): JSX.Element {
    const { visibility, is3000 } = useValues(notebookPanelLogic)
    const { toggleVisibility } = useActions(notebookPanelLogic)

    const overrides3000: Partial<LemonButtonWithSideActionProps> = is3000
        ? {
              size: 'small',
              type: 'secondary',
          }
        : {}

    return (
        <LemonButton
            icon={<IconNotebook />}
            type={visibility === 'visible' ? 'primary' : 'tertiary'}
            onClick={toggleVisibility}
            status="primary-alt"
            {...overrides3000}
        >
            {is3000 ? 'Notebooks' : null}
        </LemonButton>
    )
}
