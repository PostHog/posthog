import { useActions, useValues } from 'kea'

import { IconChevronDown, IconPin, IconPinFilled, IconTrash } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonDivider, LemonModal, LemonTag } from '@posthog/lemon-ui'

import { AccountDetailView, MAX_PINNED_VIEWS } from '../accountDetailViews'
import { accountDetailViewsLogic } from '../accountDetailViewsLogic'

function ViewRow({ view }: { view: AccountDetailView }): JSX.Element {
    const { pinnedViews, canPinMore, canEditView, viewSaving } = useValues(accountDetailViewsLogic)
    const { pinView, unpinView, moveView, deleteView } = useActions(accountDetailViewsLogic)

    const pinnedIndex = pinnedViews.findIndex((pinned) => pinned.id === view.id)
    const pinned = pinnedIndex !== -1

    const confirmDelete = (): void => {
        LemonDialog.open({
            title: `Delete "${view.name}"?`,
            description:
                view.scope === 'team'
                    ? 'This view is shared with your team. Everyone loses it.'
                    : 'This removes the view and its widgets.',
            primaryButton: {
                children: 'Delete view',
                status: 'danger',
                onClick: () => deleteView({ id: view.id }),
            },
            secondaryButton: { children: 'Cancel' },
        })
    }

    return (
        <div className="flex items-center gap-2 py-1.5" data-attr="account-detail-view-row">
            <span className="font-medium truncate">{view.name}</span>
            {view.isBuiltIn ? (
                <LemonTag size="small" type="muted">
                    Default
                </LemonTag>
            ) : null}
            <div className="ml-auto flex items-center gap-1">
                {pinned ? (
                    <>
                        <LemonButton
                            size="xsmall"
                            icon={<IconChevronDown className="rotate-180" />}
                            aria-label="Move up"
                            onClick={() => moveView(view.id, 'up')}
                            disabledReason={pinnedIndex === 0 ? 'Already first' : undefined}
                        />
                        <LemonButton
                            size="xsmall"
                            icon={<IconChevronDown />}
                            aria-label="Move down"
                            onClick={() => moveView(view.id, 'down')}
                            disabledReason={pinnedIndex === pinnedViews.length - 1 ? 'Already last' : undefined}
                        />
                    </>
                ) : null}
                <LemonButton
                    size="xsmall"
                    icon={pinned ? <IconPinFilled /> : <IconPin />}
                    tooltip={pinned ? 'Unpin from the tab strip' : 'Pin to the tab strip'}
                    aria-label={pinned ? 'Unpin view' : 'Pin view'}
                    onClick={() => (pinned ? unpinView(view.id) : pinView(view.id))}
                    disabledReason={!pinned && !canPinMore ? `You can pin up to ${MAX_PINNED_VIEWS} views` : undefined}
                    data-attr="account-detail-toggle-pin"
                />
                {!view.isBuiltIn ? (
                    <LemonButton
                        size="xsmall"
                        status="danger"
                        icon={<IconTrash />}
                        aria-label="Delete view"
                        onClick={confirmDelete}
                        disabledReason={
                            !canEditView(view)
                                ? 'Only the person who created this view can delete it'
                                : viewSaving
                                  ? 'Saving…'
                                  : undefined
                        }
                        data-attr="account-detail-delete-view"
                    />
                ) : null}
            </div>
        </div>
    )
}

export function ConfigureTabsDialog(): JSX.Element {
    const { configureTabsOpen, myViews, teamViews, pinnedViews } = useValues(accountDetailViewsLogic)
    const { setConfigureTabsOpen, setAddViewOpen } = useActions(accountDetailViewsLogic)

    return (
        <LemonModal
            isOpen={configureTabsOpen}
            onClose={() => setConfigureTabsOpen(false)}
            title="Configure tabs"
            description={`Pin up to ${MAX_PINNED_VIEWS} views to the tab strip. Unpinned views stay here.`}
            width={520}
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        onClick={() => {
                            setConfigureTabsOpen(false)
                            setAddViewOpen(true)
                        }}
                    >
                        Add view
                    </LemonButton>
                    <LemonButton type="primary" onClick={() => setConfigureTabsOpen(false)}>
                        Done
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-3">
                <span className="text-xs text-secondary">
                    {pinnedViews.length} of {MAX_PINNED_VIEWS} tabs pinned
                </span>
                <div>
                    <h4 className="text-xs font-semibold uppercase tracking-wider text-secondary mb-1">Your views</h4>
                    {myViews.length === 0 ? (
                        <p className="text-sm text-secondary mb-0">You have not created a view yet.</p>
                    ) : (
                        myViews.map((view) => <ViewRow key={view.id} view={view} />)
                    )}
                </div>
                <LemonDivider className="my-0" />
                <div>
                    <h4 className="text-xs font-semibold uppercase tracking-wider text-secondary mb-1">Team views</h4>
                    {teamViews.length === 0 ? (
                        <p className="text-sm text-secondary mb-0">Nobody on your team has shared a view yet.</p>
                    ) : (
                        teamViews.map((view) => <ViewRow key={view.id} view={view} />)
                    )}
                </div>
            </div>
        </LemonModal>
    )
}
