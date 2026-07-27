import { IconTrash, IconWarning } from '@posthog/icons'
import { LemonButton, LemonDialog } from '@posthog/lemon-ui'

interface LegacyTranslationKeysPanelProps {
    languages: string[]
    onRemove: (language: string) => void
}

export function LegacyTranslationKeysPanel({
    languages,
    onRemove,
}: LegacyTranslationKeysPanelProps): JSX.Element | null {
    if (languages.length === 0) {
        return null
    }
    return (
        <div className="flex flex-col gap-1 text-sm">
            <div className="flex items-center gap-2 text-warning font-semibold">
                <IconWarning />
                Legacy translation keys
            </div>
            <p className="m-0 text-xs text-muted">
                These codes the SDK can't match. Remove or re-add with a valid BCP-47 code (e.g. 'en', 'es-MX').
            </p>
            <div className="flex flex-wrap gap-2 mt-1">
                {languages.map((language) => (
                    <div key={language} className="flex items-center gap-1 rounded border border-border px-2 py-0.5">
                        <code className="text-xs">{language}</code>
                        <LemonButton
                            icon={<IconTrash />}
                            status="danger"
                            size="xsmall"
                            aria-label={`Remove legacy translation '${language}'`}
                            data-attr="survey-legacy-translation-remove"
                            onClick={() =>
                                LemonDialog.open({
                                    title: 'Remove legacy translation',
                                    description: (
                                        <p className="py-2">
                                            Remove the translation stored under <code>{language}</code>? It currently
                                            has no effect at runtime — the SDK never matches this code.
                                        </p>
                                    ),
                                    primaryButton: {
                                        children: 'Remove',
                                        status: 'danger',
                                        onClick: () => onRemove(language),
                                    },
                                    secondaryButton: { children: 'Cancel' },
                                })
                            }
                        />
                    </div>
                ))}
            </div>
        </div>
    )
}
