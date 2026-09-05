import { useActions, useValues } from 'kea'

import { IconCheck, IconPlus } from '@posthog/icons'
import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import {
    ACCOUNT_DETAIL_WIDGET_KINDS,
    ACCOUNT_DETAIL_WIDGET_LABELS,
    AccountDetailView,
    AccountDetailWidgetKind,
} from '../accountDetailViews'
import { accountDetailViewsLogic } from '../accountDetailViewsLogic'

const WIDGET_DESCRIPTIONS: Record<AccountDetailWidgetKind, string> = {
    text: 'Free text for whoever opens this view.',
    summary: 'The latest AI summary of the linked Slack channel.',
    usage: 'Usage metric cards for this account.',
    support_tickets: 'Support tickets matched to this account.',
    related_people: 'People in the organization behind this account.',
}

interface AddWidgetDialogProps {
    view: AccountDetailView | null
}

export function AddWidgetDialog({ view }: AddWidgetDialogProps): JSX.Element {
    const { addWidgetOpen, canEditView, viewSaving } = useValues(accountDetailViewsLogic)
    const { setAddWidgetOpen, addWidget } = useActions(accountDetailViewsLogic)

    return (
        <LemonModal
            isOpen={addWidgetOpen}
            onClose={() => setAddWidgetOpen(false)}
            title="Add widget"
            description={view ? `Widgets are added to "${view.name}".` : undefined}
            width={480}
        >
            <div className="flex flex-col gap-2">
                {ACCOUNT_DETAIL_WIDGET_KINDS.map((kind) => {
                    const added = view?.widgets.includes(kind) ?? false
                    const editable = view ? canEditView(view) : false
                    return (
                        <div key={kind} className="flex items-center gap-3 border rounded px-3 py-2">
                            <div className="min-w-0 flex flex-col">
                                <span className="font-medium">{ACCOUNT_DETAIL_WIDGET_LABELS[kind]}</span>
                                <span className="text-xs text-secondary">{WIDGET_DESCRIPTIONS[kind]}</span>
                            </div>
                            <LemonButton
                                type={added ? 'tertiary' : 'secondary'}
                                size="small"
                                icon={added ? <IconCheck /> : <IconPlus />}
                                className="ml-auto shrink-0"
                                onClick={() => view && editable && addWidget(view.id, kind)}
                                disabledReason={
                                    added
                                        ? 'Already in this view'
                                        : viewSaving
                                          ? 'Saving…'
                                          : !view
                                            ? 'No view selected'
                                            : !editable
                                              ? 'Only the person who created this view can edit it'
                                              : undefined
                                }
                                data-attr="account-detail-add-widget-kind"
                            >
                                {added ? 'Added' : 'Add'}
                            </LemonButton>
                        </div>
                    )
                })}
            </div>
        </LemonModal>
    )
}
