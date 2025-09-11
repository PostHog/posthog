import { useActions, useValues } from 'kea'

import { IconGear } from '@posthog/icons'
import { LemonButton, LemonButtonProps } from '@posthog/lemon-ui'

import { sidePanelSettingsLogic } from '~/layout/navigation-3000/sidepanel/panels/sidePanelSettingsLogic'

import { topBarSettingsButtonLogic } from './topBarSettingsButtonLogic'

interface TopBarSettingsButtonProps {
    buttonProps?: Omit<LemonButtonProps, 'children' | 'sideAction'>
    children?: React.ReactNode
}

export function TopBarSettingsButton({
    buttonProps = {
        size: 'small',
        icon: <IconGear />,
    },
    children,
}: TopBarSettingsButtonProps): JSX.Element | null {
    const { loadedSceneSettingsSectionId } = useValues(topBarSettingsButtonLogic)
    const { openSettingsPanel, closeSettingsPanel } = useActions(sidePanelSettingsLogic)
    const { isOpen } = useValues(sidePanelSettingsLogic)

    if (!loadedSceneSettingsSectionId) {
        return null
    }

    return (
        <span className="relative inline-flex">
            <LemonButton
                onClick={() =>
                    isOpen ? closeSettingsPanel() : openSettingsPanel({ sectionId: loadedSceneSettingsSectionId })
                }
                tooltip="Toggle settings"
                {...buttonProps}
            >
                {children}
            </LemonButton>
        </span>
    )
}
