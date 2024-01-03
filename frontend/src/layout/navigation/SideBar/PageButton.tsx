import { useActions, useValues } from 'kea'
import { LemonButton, LemonButtonProps, SideAction } from 'lib/lemon-ui/LemonButton'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { sceneLogic } from 'scenes/sceneLogic'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene } from 'scenes/sceneTypes'

import { navigationLogic } from '~/layout/navigation/navigationLogic'
import { SidebarChangeNoticeTooltip } from '~/layout/navigation/SideBar/SidebarChangeNotice'
import { dashboardsModel } from '~/models/dashboardsModel'

import { breadcrumbsLogic } from '../Breadcrumbs/breadcrumbsLogic'

export interface PageButtonProps extends Pick<LemonButtonProps, 'icon' | 'onClick' | 'to'> {
    /** Used for highlighting the active scene. `identifier` of type number means dashboard ID instead of scene. */
    identifier: string | number
    sideAction?: Omit<SideAction, 'type'> & { identifier?: string }
    title?: React.ReactNode
    highlight?: 'alpha' | 'beta' | 'new'
}

export function PageButton({ title, sideAction, identifier, highlight, ...buttonProps }: PageButtonProps): JSX.Element {
    const { activeScene } = useValues(sceneLogic)
    const { sceneBreadcrumbKeys } = useValues(breadcrumbsLogic)
    const { hideSideBarMobile } = useActions(navigationLogic)
    const { lastDashboardId } = useValues(dashboardsModel)

    const isActiveSide: boolean = !!sideAction?.identifier && activeScene === sideAction.identifier
    const isActive: boolean =
        isActiveSide ||
        (typeof identifier === 'string'
            ? activeScene === identifier || sceneBreadcrumbKeys.includes(identifier)
            : activeScene === Scene.Dashboard && identifier === lastDashboardId)

    title = title || sceneConfigurations[identifier]?.name || identifier

    return (
        <li>
            <SidebarChangeNoticeTooltip identifier={identifier}>
                {sideAction ? (
                    <LemonButton
                        fullWidth
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
                    </LemonButton>
                ) : (
                    <LemonButton
                        fullWidth
                        active={isActive}
                        data-attr={`menu-item-${identifier.toString().toLowerCase()}`}
                        onClick={hideSideBarMobile}
                        sideIcon={null}
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
            </SidebarChangeNoticeTooltip>
        </li>
    )
}
