import { useValues } from 'kea'
import { useContext } from 'react'

import { IconPencil } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { withInertLinks } from '../emailPreviewHtml'
import { countUnresolved, renderEmailPreviewMarked, splitUnresolved, withUnresolvedChips } from './emailPreview'
import { EmailPreviewPersonBar } from './EmailPreviewPersonBar'
import { emailPreviewPersonLogic } from './emailPreviewPersonLogic'
import { EmailPreviewScopeContext } from './EmailPreviewScopeContext'

/** The closed email editor's preview, rendered as one person with their own values filled in. */
export function EmailPersonPreview({
    html,
    text,
    onEdit,
}: {
    html: string | undefined
    text: string | undefined
    onEdit: () => void
}): JSX.Element {
    const scope = useContext(EmailPreviewScopeContext)
    const { previewPerson } = useValues(emailPreviewPersonLogic({ scope }))
    const rendered = renderEmailPreviewMarked(html || text || '', previewPerson)

    return (
        <div className="flex flex-col flex-1">
            <EmailPreviewPersonBar
                templates={[html ?? '', text ?? '']}
                unresolvedCount={countUnresolved(rendered)}
                actions={
                    <LemonButton
                        size="xsmall"
                        type="secondary"
                        icon={<IconPencil />}
                        onClick={onEdit}
                        data-attr="email-preview-edit-template"
                    >
                        Edit template
                    </LemonButton>
                }
            />
            {html ? (
                <iframe
                    srcDoc={withInertLinks(withUnresolvedChips(rendered))}
                    sandbox=""
                    title="Email preview"
                    // The recorder serializes `srcdoc`, and this one holds a real person's values.
                    className="ph-no-capture flex-1 min-h-80"
                />
            ) : (
                <pre className="ph-no-capture flex-1 min-h-80 m-0 p-4 font-sans text-sm whitespace-pre-wrap wrap-anywhere bg-surface-primary">
                    {splitUnresolved(rendered).map((part, index) =>
                        index % 2 ? (
                            <mark key={index} className="rounded px-1 bg-warning-highlight">
                                {part}
                            </mark>
                        ) : (
                            part
                        )
                    )}
                </pre>
            )}
        </div>
    )
}
