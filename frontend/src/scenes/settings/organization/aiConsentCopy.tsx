import { LemonDialog, LemonDialogProps, Tooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { Link } from 'lib/lemon-ui/Link'

export function getExternalAIProvidersTooltipTitle(): string {
    return `As of ${dayjs().format('MMMM YYYY')}: Anthropic and OpenAI`
}

export function AIHipaaDisclaimer(): JSX.Element {
    return (
        <span className="block">
            This feature is not HIPAA-compliant and is not intended for the processing of Protected Health Information
            ("PHI"). Any Business Associate Agreement ("BAA") you may have entered into with PostHog does not apply to
            this functionality. You are responsible for ensuring your use complies with applicable laws and regulations.
        </span>
    )
}

export function AIConsentPopoverDescription(): JSX.Element {
    return (
        <p className="font-medium text-pretty">
            PostHog AI needs your approval to potentially process identifying user data with{' '}
            <Tooltip title={getExternalAIProvidersTooltipTitle()}>
                <dfn>external AI providers</dfn>
            </Tooltip>
            . <i>Your data won't be used for training models.</i>
        </p>
    )
}

export function AIConsentSettingsDescription(): JSX.Element {
    return (
        <span className="flex flex-col gap-2 max-w-prose">
            <span className="block">
                PostHog AI features, such as the PostHog AI chat, use{' '}
                <Tooltip title={getExternalAIProvidersTooltipTitle()}>
                    <dfn>external AI services</dfn>
                </Tooltip>{' '}
                for data analysis.
            </span>
            <span className="block">
                This <i>can</i> involve transfer of identifying user data, so we ask for your org-wide consent below.
            </span>
            <span className="block">
                <strong>Your data will not be used for training models.</strong>
            </span>
            <AIHipaaDisclaimer />
        </span>
    )
}

export function aiConsentLegalDialogProps({ onConfirm }: { onConfirm: () => void }): LemonDialogProps {
    return {
        title: 'The legal bits',
        maxWidth: '65ch',
        content: (
            <div className="flex flex-col gap-2">
                <p className="mb-0">
                    If your org requires a Data Processing Agreement (DPA) for compliance (and your existing DPA doesn't
                    already cover AI subprocessors),{' '}
                    <Link to="https://posthog.com/dpa" target="_blank">
                        you can get a fresh DPA here
                    </Link>
                    .
                </p>
                <AIHipaaDisclaimer />
            </div>
        ),
        primaryButton: {
            children: 'Enable AI analysis',
            'data-attr': 'ai-consent-legal-confirm',
            onClick: onConfirm,
        },
        secondaryButton: {
            children: 'Cancel',
            'data-attr': 'ai-consent-legal-cancel',
        },
    }
}

export function openAIConsentLegalDialog(args: { onConfirm: () => void }): void {
    LemonDialog.open(aiConsentLegalDialogProps(args))
}
