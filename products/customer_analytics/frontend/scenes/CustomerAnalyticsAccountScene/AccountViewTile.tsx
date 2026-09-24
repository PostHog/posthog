import { useActions, useValues } from 'kea'

import { IconEllipsis, IconPencil, IconTrash } from '@posthog/icons'
import { LemonButton, LemonCard, LemonDialog, LemonMenu, type LemonMenuItems } from '@posthog/lemon-ui'

import { AccountViewComponent } from '../../components/Accounts/AccountViewComponent'
import { getAccountViewComponentByKind } from '../../components/Accounts/accountViewComponents'
import type { AccountViewApi } from '../../generated/api.schemas'
import type { AccountViewComponentInstance } from './accountViewDocument'
import { accountViewsLogic } from './accountViewsLogic'

interface AccountViewTileProps {
    view: AccountViewApi
    component: AccountViewComponentInstance
    componentCount: number
    projectId: number
    accountId: string
    externalId: string
    spanClassName: string
}

export function AccountViewTile({
    view,
    component,
    componentCount,
    projectId,
    accountId,
    externalId,
    spanClassName,
}: AccountViewTileProps): JSX.Element {
    const logic = accountViewsLogic({ projectId })
    const { tileSaving } = useValues(logic)
    const { openTileEditor, removeViewComponent } = useActions(logic)
    const title = component.title ?? getAccountViewComponentByKind(component.kind)?.label ?? component.kind
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
                    onClick: () => openTileEditor(view.id, component.nodeId, title),
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
        <LemonCard hoverEffect={false} className={`col-span-12 min-w-0 overflow-hidden p-0 ${spanClassName}`}>
            <div className="flex items-center gap-2 border-b px-2 py-1">
                <span className="min-w-0 flex-1 truncate text-xs font-medium text-secondary">{title}</span>
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
            <div className="min-w-0 px-2 pt-2 pb-0 [&_.LemonTable]:-mx-2 [&_.LemonTable]:!w-[calc(100%+1rem)]">
                <AccountViewComponent kind={component.kind} accountId={accountId} externalId={externalId} embedded />
            </div>
        </LemonCard>
    )
}
