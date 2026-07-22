import { useActions, useValues } from 'kea'

import { IconEye } from '@posthog/icons'

import { CodeSnippet } from 'lib/components/CodeSnippet'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { SceneExport } from 'scenes/sceneTypes'

import { revealSecretLogic } from './revealSecretLogic'

export const scene: SceneExport = {
    component: RevealSecret,
    logic: revealSecretLogic,
}

interface SecretTypeCopy {
    title: string
    label: string
    description: string
}

// Type-specific copy for the reveal page. Keep the keys in sync with the backend `OneTimeSecretType`.
const SECRET_TYPE_COPY: Record<string, SecretTypeCopy> = {
    personal_api_token: {
        title: 'Your new personal API key',
        label: 'personal API key',
        description:
            'This is a one-time reveal. Once you reveal it on this page it can never be shown here again, so copy it somewhere safe.',
    },
}

const FALLBACK_COPY: SecretTypeCopy = {
    title: 'Your one-time secret',
    label: 'secret',
    description:
        'This is a one-time reveal. Once you reveal it on this page it can never be shown here again, so copy it somewhere safe.',
}

function copyForType(secretType?: string): SecretTypeCopy {
    return (secretType ? SECRET_TYPE_COPY[secretType] : undefined) ?? FALLBACK_COPY
}

export function RevealSecret(): JSX.Element {
    const { secretMeta, secretMetaLoading, revealedSecret, revealedSecretLoading, unavailable } =
        useValues(revealSecretLogic)
    const { reveal } = useActions(revealSecretLogic)

    const copy = copyForType(revealedSecret?.secret_type ?? secretMeta?.secret_type)

    return (
        <div className="flex items-center justify-center min-h-screen p-4">
            <div className="w-full max-w-lg border rounded bg-surface-primary p-6 deprecated-space-y-4">
                {secretMetaLoading ? (
                    <div className="flex justify-center py-8">
                        <Spinner className="text-2xl" />
                    </div>
                ) : unavailable ? (
                    <>
                        <h2 className="text-xl font-semibold mb-0">This link is no longer available</h2>
                        <LemonBanner type="warning">
                            This secret link has expired or has already been revealed. One-time secrets can only be
                            viewed once — if you still need it, generate a new one.
                        </LemonBanner>
                    </>
                ) : revealedSecret ? (
                    <>
                        <h2 className="text-xl font-semibold mb-0">{copy.title}</h2>
                        <p className="text-muted">Copy your {copy.label} now — this is the only time it's shown.</p>
                        <CodeSnippet thing={copy.label} className="ph-no-capture">
                            {revealedSecret.value}
                        </CodeSnippet>
                        <LemonBanner type="warning">
                            This {copy.label} has now been revealed and can never be shown here again. If you didn't
                            copy it, generate a new one.
                        </LemonBanner>
                    </>
                ) : (
                    <>
                        <h2 className="text-xl font-semibold mb-0">{copy.title}</h2>
                        <p className="text-muted">{copy.description}</p>
                        <div className="font-mono text-lg tracking-widest text-muted bg-surface-secondary rounded p-3 text-center select-none">
                            ••••••••••••••••••••••••
                        </div>
                        <LemonButton
                            type="primary"
                            fullWidth
                            center
                            icon={<IconEye />}
                            loading={revealedSecretLoading}
                            onClick={() => reveal()}
                        >
                            Reveal {copy.label}
                        </LemonButton>
                        <p className="text-xs text-muted text-center mb-0">
                            Revealing displays the value once and permanently consumes this link.
                        </p>
                    </>
                )}
            </div>
        </div>
    )
}
