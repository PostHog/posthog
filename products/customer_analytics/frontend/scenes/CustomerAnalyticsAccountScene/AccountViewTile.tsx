import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconEllipsis, IconPencil, IconTrash } from '@posthog/icons'
import { LemonButton, LemonCard, LemonDialog, LemonMenu, type LemonMenuItems } from '@posthog/lemon-ui'

import { AccountViewComponent } from '../../components/Accounts/AccountViewComponent'
import { getAccountViewComponentByKind } from '../../components/Accounts/accountViewComponents'
import type { AccountViewApi } from '../../generated/api.schemas'
import type { AccountViewComponentInstance } from './accountViewDocument'
import { accountViewsLogic } from './accountViewsLogic'
import { accountViewTileHeaderContext } from './accountViewTileHeaderContext'

interface AccountViewTileProps {
    view: AccountViewApi
    component: AccountViewComponentInstance
    instanceId: string
    componentCount: number
    projectId: number
    accountId: string
    externalId: string
    spanClassName: string
}

export function AccountViewTile({
    view,
    component,
    instanceId,
    componentCount,
    projectId,
    accountId,
    externalId,
    spanClassName,
}: AccountViewTileProps): JSX.Element {
    const [headerActionsTarget, setHeaderActionsTarget] = useState<HTMLDivElement | null>(null)
    const logic = accountViewsLogic({ projectId })
    const { tileSaving } = useValues(logic)
    const { openTileEditor, removeViewComponent, updateViewComponentConfig } = useActions(logic)
    const definition = getAccountViewComponentByKind(component.kind)
    const title = component.title ?? definition?.label ?? component.kind
    const insetClassName = definition?.tileInsetClassName ?? 'px-2'
    const menuDisabledReason = !view.can_edit ? 'You cannot edit this view' : tileSaving ? 'Saving changes' : undefined

    const confirmRemove = (): void => {
        LemonDialog.open({
            title: `Remove "${title}" from view?`,
            description: 'This removes the tile from this view.',
            primaryButton: {
                children: 'Remove from view',
                status: 'danger',
                onClick: () => removeViewComponent(view.id, component.nodeId),
            },
            secondaryButton: { children: 'Cancel' },
        })
    }

    const items: LemonMenuItems = [
        {
            items: [
                {
                    label: 'Edit',
                    icon: <IconPencil />,
                    onClick: () =>
                        openTileEditor(
                            view.id,
                            component.nodeId,
                            title,
                            definition?.ConfigEditor
                                ? { kind: component.kind, config: component.config ?? {}, accountId }
                                : undefined
                        ),
                    disabledReason: menuDisabledReason,
                },
                {
                    label: 'Remove from view',
                    icon: <IconTrash />,
                    status: 'danger',
                    onClick: confirmRemove,
                    disabledReason:
                        menuDisabledReason ?? (componentCount === 1 ? 'A view needs at least one tile' : undefined),
                },
            ],
        },
    ]

    return (
        <accountViewTileHeaderContext.Provider value={headerActionsTarget}>
            <LemonCard hoverEffect={false} className={`col-span-12 min-w-0 overflow-hidden p-0 ${spanClassName}`}>
                <div className={clsx('flex items-center gap-2 border-b py-1', insetClassName)}>
                    <span className="min-w-0 flex-1 truncate text-xs font-medium text-secondary">{title}</span>
                    <div ref={setHeaderActionsTarget} className="flex shrink-0 items-center gap-2" />
                    <LemonMenu items={items}>
                        <LemonButton
                            type="tertiary"
                            size="xsmall"
                            icon={<IconEllipsis />}
                            loading={tileSaving}
                            disabledReason={menuDisabledReason}
                            aria-label="Tile actions"
                            data-attr="account-view-tile-actions"
                        />
                    </LemonMenu>
                </div>
                <div
                    className={clsx(
                        'min-w-0 pt-2 pb-0 [&_.LemonTable]:-mx-2 [&_.LemonTable]:!w-[calc(100%+1rem)]',
                        insetClassName
                    )}
                >
                    <AccountViewComponent
                        kind={component.kind}
                        accountId={accountId}
                        projectId={projectId}
                        externalId={externalId}
                        instanceId={instanceId}
                        initialConfig={component.config}
                        onConfigChange={
                            view.can_edit
                                ? (config) => updateViewComponentConfig(view.id, component.nodeId, config)
                                : undefined
                        }
                        embedded
                    />
                </div>
            </LemonCard>
        </accountViewTileHeaderContext.Provider>
    )
}
