import { IconNotebook } from 'lib/lemon-ui/icons'
import { useActions, useValues } from 'kea'
import { notebookPopoverLogic } from 'scenes/notebooks/Notebook/notebookPopoverLogic'
import { LemonButton, LemonButtonWithSideActionProps } from '@posthog/lemon-ui'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'

export function NotebookButton(): JSX.Element {
    const { visibility } = useValues(notebookPopoverLogic)
    const { setVisibility } = useActions(notebookPopoverLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const overrides3000: Partial<LemonButtonWithSideActionProps> = featureFlags[FEATURE_FLAGS.POSTHOG_3000]
        ? {
              size: 'small',
              type: 'secondary',
          }
        : {}

    return (
        <LemonButton
            icon={<IconNotebook />}
            type={visibility === 'visible' ? 'primary' : 'tertiary'}
            onClick={() => setVisibility(visibility === 'visible' ? 'hidden' : 'visible')}
            status="primary-alt"
            {...overrides3000}
        >
            {featureFlags[FEATURE_FLAGS.POSTHOG_3000] ? 'Notebooks' : null}
        </LemonButton>
    )
}
