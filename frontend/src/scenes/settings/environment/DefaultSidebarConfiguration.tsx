import { useActions, useValues } from 'kea'

import { LemonButton, LemonDialog, LemonTag } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { teamLogic } from 'scenes/teamLogic'

import { UI_CONFIGURATION_VERSION, uiCustomizationLogic } from '~/layout/uiCustomizationLogic'
import { UserUIConfiguration } from '~/queries/schema/schema-general'

/**
 * Admin-only: publish a sidebar layout as the project default. Members who haven't customized
 * their own sidebar inherit it; personal customizations are layered on top and always win.
 */
export function DefaultSidebarConfiguration(): JSX.Element {
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const { uiConfiguration } = useValues(uiCustomizationLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    const hasProjectDefault = !!currentTeam?.default_ui_configuration

    const saveCurrentAsDefault = (): void => {
        // Only the sidebar layout becomes the project default: per-project accent colors are
        // personal preferences, and pinned groups reference the admin's own pins, which no other
        // member can resolve.
        const { groups: _groups, ...sidebar } = uiConfiguration?.sidebar ?? {}
        const configuration: UserUIConfiguration | null = uiConfiguration?.sidebar
            ? { version: UI_CONFIGURATION_VERSION, sidebar }
            : null
        LemonDialog.open({
            title: 'Set your current sidebar as the project default?',
            description:
                'Members who haven’t customized their sidebar will get this layout. Personal customizations always take precedence.',
            primaryButton: {
                children: 'Set as default',
                onClick: () => updateCurrentTeam({ default_ui_configuration: configuration }),
            },
            secondaryButton: { children: 'Cancel' },
        })
    }

    return (
        <div className="flex flex-col gap-2 max-w-160">
            <div className="flex items-center gap-2">
                {hasProjectDefault ? (
                    <LemonTag type="success">A project default is set</LemonTag>
                ) : (
                    <LemonTag>No project default set</LemonTag>
                )}
            </div>
            <div className="flex gap-2">
                <LemonButton
                    type="primary"
                    size="small"
                    disabledReason={
                        restrictedReason ?? (!uiConfiguration?.sidebar ? 'Customize your own sidebar first' : undefined)
                    }
                    loading={currentTeamLoading}
                    onClick={saveCurrentAsDefault}
                    data-attr="default-sidebar-configuration-save"
                >
                    Use my current sidebar as the default
                </LemonButton>
                {hasProjectDefault && (
                    <LemonButton
                        type="secondary"
                        status="danger"
                        size="small"
                        disabledReason={restrictedReason}
                        loading={currentTeamLoading}
                        onClick={() =>
                            LemonDialog.open({
                                title: 'Clear the project default sidebar?',
                                description: 'Members without their own customization go back to the standard layout.',
                                primaryButton: {
                                    children: 'Clear default',
                                    status: 'danger',
                                    onClick: () => updateCurrentTeam({ default_ui_configuration: null }),
                                },
                                secondaryButton: { children: 'Cancel' },
                            })
                        }
                        data-attr="default-sidebar-configuration-clear"
                    >
                        Clear project default
                    </LemonButton>
                )}
            </div>
        </div>
    )
}
