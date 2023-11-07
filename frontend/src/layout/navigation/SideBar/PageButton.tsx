import { useActions, useValues } from 'kea'
import { sceneLogic } from 'scenes/sceneLogic'
import { navigationLogic } from '~/layout/navigation/navigationLogic'
import { dashboardsModel } from '~/models/dashboardsModel'
import { Scene } from 'scenes/sceneTypes'
import { LemonButton, LemonButtonProps, LemonButtonWithSideAction, SideAction } from 'lib/lemon-ui/LemonButton'
import { sceneConfigurations } from 'scenes/scenes'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'

export interface PageButtonProps extends Pick<LemonButtonProps, 'icon' | 'onClick' | 'to'> {
    /** Used for highlighting the active scene. `identifier` of type number means dashboard ID instead of scene. */
    identifier: string | number
    sideAction?: Omit<SideAction, 'type'> & { identifier?: string }
    title?: React.ReactNode
    highlight?: 'alpha' | 'beta' | 'new'
}

export function PageButton({ title, sideAction, identifier, highlight, ...buttonProps }: PageButtonProps): JSX.Element {
    const { aliasedActiveScene, activeScene } = useValues(sceneLogic)
    const { hideSideBarMobile } = useActions(navigationLogic)
    const { lastDashboardId } = useValues(dashboardsModel)

    const isActiveSide: boolean = sideAction?.identifier === aliasedActiveScene
    const isActive: boolean =
        isActiveSide ||
        (typeof identifier === 'string'
            ? identifier === aliasedActiveScene
            : activeScene === Scene.Dashboard && identifier === lastDashboardId)

    const buttonStatus = isActive ? 'primary' : 'stealth'
    title = title || sceneConfigurations[identifier]?.name || identifier

    return (
        <li>
            {sideAction ? (
                <LemonButtonWithSideAction
                    fullWidth
                    status={buttonStatus}
                    active={isActive}
                    onClick={hideSideBarMobile}
                    sideAction={{
                        ...sideAction,
                        'data-attr': sideAction.identifier
                            ? `menu-item-${sideAction.identifier.toLowerCase()}`
                            : undefined,
                    }}
                    data-attr={`menu-item-${identifier.toString().toLowerCase()}`}
                    {...buttonProps}
                >
                    <span className="text-default">{title}</span>
                </LemonButtonWithSideAction>
            ) : (
                <LemonButton
                    fullWidth
                    status={buttonStatus}
                    active={isActive}
                    data-attr={`menu-item-${identifier.toString().toLowerCase()}`}
                    onClick={hideSideBarMobile}
                    {...buttonProps}
                >
                    <span className="text-default grow">{title}</span>
                    {highlight === 'alpha' ? (
                        <LemonTag type="completion" className="ml-1 float-right uppercase">
                            Alpha
                        </LemonTag>
                    ) : highlight === 'beta' ? (
                        <LemonTag type="warning" className="ml-1 float-right uppercase">
                            Beta
                        </LemonTag>
                    ) : highlight === 'new' ? (
                        <LemonTag type="success" className="ml-1 float-right uppercase">
                            New
                        </LemonTag>
                    ) : null}
                </LemonButton>
            )}
        </li>
    )
}
