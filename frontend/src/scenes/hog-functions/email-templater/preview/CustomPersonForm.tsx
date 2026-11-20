import { useActions, useValues } from 'kea'
import { useContext, useState } from 'react'

import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { propertiesUsed } from './emailPreview'
import { emailPreviewPersonLogic } from './emailPreviewPersonLogic'
import { EmailPreviewScopeContext } from './EmailPreviewScopeContext'

export function CustomPersonForm({ templates, onDone }: { templates: string[]; onDone: () => void }): JSX.Element {
    const scope = useContext(EmailPreviewScopeContext)
    const { customProperties } = useValues(emailPreviewPersonLogic({ scope }))
    const { setCustomProperties } = useActions(emailPreviewPersonLogic({ scope }))
    const keys = propertiesUsed(templates)
    const [draft, setDraft] = useState<Record<string, string>>(customProperties ?? {})

    if (keys.length === 0) {
        return <span className="text-muted text-xs">This email doesn't use any person or event properties.</span>
    }
    return (
        <div className="flex flex-col gap-1">
            {keys.map((key) => (
                <LemonInput
                    key={key}
                    size="small"
                    placeholder={key.replace('.properties.', ' ')}
                    value={draft[key] ?? ''}
                    onChange={(value) => setDraft({ ...draft, [key]: value })}
                />
            ))}
            <LemonButton
                type="primary"
                size="small"
                center
                onClick={() => {
                    setCustomProperties(draft)
                    onDone()
                }}
                data-attr="email-preview-custom-person"
            >
                Preview as custom person
            </LemonButton>
        </div>
    )
}
