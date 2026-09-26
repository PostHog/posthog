import { useActions } from 'kea'

import { IconEllipsis, IconGear } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { navAppsTabLogic } from './navAppsTabLogic'

export function NavAppsMenu(): JSX.Element {
    const { setConfigureStarredOpen } = useActions(navAppsTabLogic)

    return (
        <LemonMenu
            placement="bottom-end"
            items={[
                {
                    label: 'Configure starred',
                    icon: <IconGear />,
                    onClick: () => setConfigureStarredOpen(true),
                },
            ]}
        >
            <LemonButton
                size="xsmall"
                icon={<IconEllipsis />}
                tooltip="Starred options"
                aria-label="Starred options"
                data-attr="nav-apps-starred-options"
            />
        </LemonMenu>
    )
}
