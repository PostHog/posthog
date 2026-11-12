import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconCopy, IconEllipsis, IconPencil, IconTrash } from '@posthog/icons'
import { LemonButton, LemonCard, LemonDialog, LemonMenu, type LemonMenuItems } from '@posthog/lemon-ui'

import { LemonTableLoader } from 'lib/lemon-ui/LemonTable/LemonTableLoader'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { cn } from 'lib/utils/css-classes'

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
    const [widgetLoading, setWidgetLoading] = useState(false)
    const logic = accountViewsLogic({ projectId })
    const { tileSaving } = useValues(logic)
    const { openTileEditor, removeViewComponent, duplicateViewComponent, updateViewComponentConfig } = useActions(logic)
    const definition = getAccountViewComponentByKind(component.kind)
    const title = component.title ?? definition?.label ?? component.kind
    const insetClassName = definition?.tileInsetClassName ?? 'px-2'
    const menuDisabledReason = !view.can_edit ? 'You cannot edit this view' : tileSaving ? 'Saving changes' : undefined

    const editTile = (): void => {
        openTileEditor(
            view.id,
            component.nodeId,
            title,
            definition?.ConfigEditor ? { kind: component.kind, config: component.config ?? {}, accountId } : undefined
        )
    }

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
                    onClick: editTile,
                    disabledReason: menuDisabledReason,
                },
                ...(definition?.canDuplicate
                    ? [
                          {
                              label: 'Duplicate',
                              icon: <IconCopy />,
                              onClick: () => duplicateViewComponent(view.id, component.nodeId),
                              disabledReason: menuDisabledReason,
                          },
                      ]
                    : []),
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
                <div className={clsx('relative flex items-center gap-2 border-b py-1', insetClassName)}>
                    <span className="flex min-w-0 flex-1 items-center gap-1.5 text-xs font-medium text-secondary">
                        <span className="truncate">{title}</span>
                        {widgetLoading ? (
                            <span className="inline-flex shrink-0 items-center text-accent" role="status">
                                <Spinner className="mr-1.5 text-base" textColored />
                                Loading
                            </span>
                        ) : null}
                    </span>
                    {definition?.showHeaderEdit && (
                        <LemonButton
                            type="tertiary"
                            size="xsmall"
                            icon={<IconPencil />}
                            onClick={editTile}
                            disabledReason={menuDisabledReason}
                            tooltip="Edit tile"
                            aria-label="Edit tile"
                            data-attr="account-view-tile-edit"
                        />
                    )}
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
                    <LemonTableLoader loading={widgetLoading} />
                </div>
                <div
                    className={cn(
                        'min-w-0 pt-2 pb-0',
                        definition?.tileContentClassName ?? [
                            insetClassName,
                            '[&_.LemonTable]:-mx-2 [&_.LemonTable]:!w-[calc(100%+1rem)]',
                        ]
                    )}
                >
                    <AccountViewComponent
                        kind={component.kind}
                        accountId={accountId}
                        projectId={projectId}
                        externalId={externalId}
                        instanceId={instanceId}
                        initialConfig={component.config}
                        onLoadingChange={setWidgetLoading}
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
