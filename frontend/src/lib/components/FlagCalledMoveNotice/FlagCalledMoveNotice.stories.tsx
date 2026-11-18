import { Meta, StoryObj } from '@storybook/react'

import { FlagCalledMoveNotice } from 'lib/components/FlagCalledMoveNotice/FlagCalledMoveNotice'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { FEATURE_FLAGS } from 'lib/constants'

type Story = StoryObj<{}>
const meta: Meta = {
    title: 'Components/Flag Called Move Notice',
    parameters: {
        featureFlags: [FEATURE_FLAGS.FLAG_CALLED_MOVE_NOTICES],
    },
}
export default meta

export const UnderAnEventDescription: Story = {
    render: () => (
        // DefinitionPopover.scss caps the definition popover at this width (20rem), so the notice wraps as it does there.
        <div className="w-80 border rounded p-3 bg-surface-primary">
            <p>Sent by PostHog SDKs each time a feature flag is evaluated.</p>
            <FlagCalledMoveNotice name="$feature_flag_called" groupType={TaxonomicFilterGroupType.Events} />
        </div>
    ),
}
