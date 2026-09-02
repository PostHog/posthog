import { useActions } from 'kea'

import { IconNotebook } from '@posthog/icons'
import { LemonDialog, LemonTextArea } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

import { AccountDetailView } from '../accountDetailViews'
import { accountDetailViewsLogic } from '../accountDetailViewsLogic'
import { AccountWidgetCard } from './AccountWidgetCard'

interface AccountTextWidgetProps {
    view: AccountDetailView
    onRemove: () => void
}

export function AccountTextWidget({ view, onRemove }: AccountTextWidgetProps): JSX.Element {
    const { setViewText } = useActions(accountDetailViewsLogic)

    const openEditor = (): void => {
        LemonDialog.openForm({
            title: 'Edit text',
            initialValues: { text: view.text },
            content: (
                <LemonField name="text">
                    <LemonTextArea placeholder="Notes for whoever opens this view. Markdown works." minRows={4} />
                </LemonField>
            ),
            onSubmit: ({ text }) => setViewText(view.id, text ?? ''),
        })
    }

    return (
        <AccountWidgetCard
            wide
            icon={<IconNotebook />}
            title="Text"
            onConfigure={openEditor}
            onRemove={onRemove}
            data-attr="account-text-widget"
        >
            {view.text ? (
                <LemonMarkdown lowKeyHeadings disableImages disableDocsRedirect className="text-sm px-3 py-3">
                    {view.text}
                </LemonMarkdown>
            ) : (
                <p className="text-sm text-secondary p-3 mb-0">
                    Nothing written yet. Use Configure in the widget menu to add text for this view.
                </p>
            )}
        </AccountWidgetCard>
    )
}
