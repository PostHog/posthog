import { useActions, useValues } from 'kea'

import { IconEllipsis } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LemonMenu } from 'lib/lemon-ui/LemonMenu'

import { CustomerProfileScope } from '~/types'

import { pinnedProfilePropertiesLogic } from '../../pinnedProfilePropertiesLogic'

export function PinnedPropertiesMenu({ scope }: { scope: CustomerProfileScope }): JSX.Element {
    const logic = pinnedProfilePropertiesLogic({ scope })
    const { hasOwnPins, teamPinnedProperties, savingTeamDefault } = useValues(logic)
    const { setAsTeamDefault, useTeamDefault } = useActions(logic)

    return (
        <LemonMenu
            items={[
                {
                    label: 'Set as team default',
                    tooltip: 'Everyone on this team sees these pinned properties until they pin their own.',
                    disabledReason: savingTeamDefault ? 'Saving' : undefined,
                    onClick: setAsTeamDefault,
                    'data-attr': 'pinned-properties-set-team-default',
                },
                {
                    label: 'Use team default',
                    tooltip: 'Drop the pins you made here and follow the team default again.',
                    disabledReason: !hasOwnPins
                        ? 'You have no pins of your own here'
                        : !teamPinnedProperties
                          ? 'Your team has no default yet'
                          : undefined,
                    onClick: useTeamDefault,
                    'data-attr': 'pinned-properties-use-team-default',
                },
            ]}
        >
            <LemonButton
                size="xsmall"
                icon={<IconEllipsis />}
                tooltip="Pinned property options"
                aria-label="Pinned property options"
            />
        </LemonMenu>
    )
}
