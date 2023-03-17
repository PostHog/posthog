import { IconJournal } from 'lib/lemon-ui/icons'
import { useActions, useValues } from 'kea'
import { notebookSidebarLogic } from 'scenes/notebooks/Notebook/notebookSidebarLogic'
import { LemonButton, LemonButtonWithSideActionProps } from '@posthog/lemon-ui'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'

export function NotebookButton(): JSX.Element {
    const { notebookSideBarShown } = useValues(notebookSidebarLogic)
    const { setNotebookSideBarShown } = useActions(notebookSidebarLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const overrides3000: Partial<LemonButtonWithSideActionProps> = featureFlags[FEATURE_FLAGS.POSTHOG_3000]
        ? {
              size: 'small',
          }
        : {}
    return (
        <LemonButton
            type="secondary"
            icon={<IconJournal />}
            onClick={() => setNotebookSideBarShown(!notebookSideBarShown)}
            {...overrides3000}
        >
            Notebooks
        </LemonButton>
    )
}
