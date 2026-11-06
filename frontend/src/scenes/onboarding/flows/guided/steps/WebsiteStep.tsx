import { useActions, useValues } from 'kea'

import { Button, Field, FieldDescription, FieldError, FieldLabel, Input } from '@posthog/quill'

import { StepLayout } from '../components/StepLayout'
import { guidedOnboardingLogic } from '../guidedOnboardingLogic'

export function WebsiteStep(): JSX.Element {
    const { resolvedWebsiteUrl, websiteUrlError, displayName } = useValues(guidedOnboardingLogic)
    const { setWebsiteUrl, submitWebsiteUrl } = useActions(guidedOnboardingLogic)

    return (
        <StepLayout
            title={`What's the address of ${displayName}?`}
            description="Web analytics only counts traffic from websites you add here. You can add more later."
            primary={
                <Button
                    variant="primary"
                    onClick={submitWebsiteUrl}
                    disabledReason={
                        !resolvedWebsiteUrl.trim() ? 'Enter your website address' : websiteUrlError || undefined
                    }
                    data-attr="guided-onboarding-website-continue"
                >
                    Continue
                </Button>
            }
        >
            <Field data-invalid={!!websiteUrlError || undefined}>
                <FieldLabel htmlFor="guided-onboarding-website-url">Website address</FieldLabel>
                <Input
                    id="guided-onboarding-website-url"
                    type="url"
                    autoFocus
                    placeholder="https://example.com"
                    value={resolvedWebsiteUrl}
                    aria-invalid={!!websiteUrlError}
                    onChange={(event) => setWebsiteUrl(event.target.value)}
                    onKeyDown={(event) => event.key === 'Enter' && submitWebsiteUrl()}
                    data-attr="guided-onboarding-website-url"
                />
                {websiteUrlError ? (
                    <FieldError>{websiteUrlError}</FieldError>
                ) : (
                    <FieldDescription>Use the full address with https, without a path or wildcards.</FieldDescription>
                )}
            </Field>
        </StepLayout>
    )
}
