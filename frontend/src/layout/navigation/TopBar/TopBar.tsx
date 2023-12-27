import './TopBar.scss'

import { LemonButtonWithDropdown, Lettermark } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { CommandPalette } from 'lib/components/CommandPalette/CommandPalette'
import { organizationLogic } from 'scenes/organizationLogic'

import { ProjectSwitcherOverlay } from '../ProjectSwitcher'
import { Announcement } from './Announcement'
import { topBarLogic } from './topBarLogic'

export function TopBar(): JSX.Element {
    const { currentOrganization } = useValues(organizationLogic)
    const { isProjectSwitcherShown } = useValues(topBarLogic)
    const { toggleProjectSwitcher, hideProjectSwitcher } = useActions(topBarLogic)

    return (
        <>
            <Announcement />
            <header className="TopBar">
                <div className="TopBar__segment TopBar__segment--right">
                    {currentOrganization?.teams && currentOrganization.teams.length > 1 && (
                        <div>
                            <LemonButtonWithDropdown
                                icon={<Lettermark name={currentOrganization?.name} />}
                                onClick={() => toggleProjectSwitcher()}
                                dropdown={{
                                    visible: isProjectSwitcherShown,
                                    onClickOutside: hideProjectSwitcher,
                                    overlay: <ProjectSwitcherOverlay onClickInside={hideProjectSwitcher} />,
                                    actionable: true,
                                    placement: 'top-end',
                                }}
                                type="secondary"
                                fullWidth
                            >
                                <span className="text-muted">Switch project</span>
                            </LemonButtonWithDropdown>
                        </div>
                    )}
                </div>
            </header>
            <CommandPalette />
        </>
    )
}
