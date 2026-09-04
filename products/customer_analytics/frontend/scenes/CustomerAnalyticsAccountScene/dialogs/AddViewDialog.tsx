import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonCheckbox, LemonInput, LemonLabel, LemonModal, LemonSegmentedButton } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import {
    ACCOUNT_DETAIL_WIDGET_KINDS,
    ACCOUNT_DETAIL_WIDGET_LABELS,
    AccountDetailViewScope,
    AccountDetailWidgetKind,
    MAX_PINNED_VIEWS,
} from '../accountDetailViews'
import { accountDetailViewsLogic } from '../accountDetailViewsLogic'

export function AddViewDialog(): JSX.Element {
    const { addViewOpen, newViewForm, canPinMore, viewSaving } = useValues(accountDetailViewsLogic)
    const { setAddViewOpen, setNewViewFormValue, submitNewViewForm, resetNewViewForm } =
        useActions(accountDetailViewsLogic)

    const close = (): void => {
        setAddViewOpen(false)
        resetNewViewForm()
    }

    const toggleWidget = (kind: AccountDetailWidgetKind, checked: boolean): void => {
        const widgets = checked
            ? [...newViewForm.widgets, kind]
            : newViewForm.widgets.filter((widget) => widget !== kind)
        setNewViewFormValue('widgets', widgets)
    }

    return (
        <LemonModal
            isOpen={addViewOpen}
            onClose={close}
            title="Add view"
            description="A view is a tab with its own set of widgets."
            width={480}
            footer={
                <>
                    <LemonButton type="secondary" onClick={close}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={submitNewViewForm}
                        loading={viewSaving}
                        disabledReason={
                            viewSaving
                                ? 'Saving…'
                                : newViewForm.widgets.length === 0
                                  ? 'Pick at least one widget'
                                  : undefined
                        }
                        data-attr="account-detail-create-view"
                    >
                        Create view
                    </LemonButton>
                </>
            }
        >
            <Form logic={accountDetailViewsLogic} formKey="newViewForm" className="flex flex-col gap-4">
                <LemonField name="name" label="Name">
                    <LemonInput placeholder="Renewal watch" autoFocus data-attr="account-detail-view-name" />
                </LemonField>
                <LemonField name="scope" label="Who can see it">
                    <LemonSegmentedButton<AccountDetailViewScope>
                        value={newViewForm.scope}
                        onChange={(scope) => setNewViewFormValue('scope', scope)}
                        options={[
                            { value: 'personal', label: 'Only me' },
                            { value: 'team', label: 'Everyone in the team' },
                        ]}
                        size="small"
                    />
                </LemonField>
                <div className="flex flex-col gap-1">
                    <LemonLabel>Widgets</LemonLabel>
                    {ACCOUNT_DETAIL_WIDGET_KINDS.map((kind) => (
                        <LemonCheckbox
                            key={kind}
                            checked={newViewForm.widgets.includes(kind)}
                            onChange={(checked) => toggleWidget(kind, checked)}
                            label={ACCOUNT_DETAIL_WIDGET_LABELS[kind]}
                            size="small"
                        />
                    ))}
                </div>
                <LemonCheckbox
                    checked={newViewForm.pin && canPinMore}
                    onChange={(checked) => setNewViewFormValue('pin', checked)}
                    label="Pin it to the tab strip"
                    disabledReason={!canPinMore ? `All ${MAX_PINNED_VIEWS} tab slots are taken` : undefined}
                    size="small"
                />
            </Form>
        </LemonModal>
    )
}
