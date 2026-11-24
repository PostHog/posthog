import { useActions, useValues } from 'kea'
import { useId } from 'react'

import {
    Button,
    Card,
    CardContent,
    CardHeader,
    CardTitle,
    Checkbox,
    Field,
    FieldLabel,
    Heading,
    Text,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { proxyLogic } from './proxyLogic'

function InlineLink({ to, children }: { to: string; children: string }): JSX.Element {
    return (
        <Button variant="link" size="inline" nativeButton={false} render={<LinkPrimitive to={to} target="_blank" />}>
            {children}
        </Button>
    )
}

export function QuillCloudflareOptIn({
    onAcknowledge,
    restrictionReason,
}: {
    onAcknowledge: () => void
    restrictionReason: string | false | undefined | null
}): JSX.Element {
    const { cloudflareOptInChecked } = useValues(proxyLogic)
    const { setCloudflareOptInChecked } = useActions(proxyLogic)
    const checkboxId = useId()

    return (
        <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-2">
                <Heading size="sm" render={<h3 className="m-0" />}>
                    Enable Managed Proxy
                </Heading>
                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                    This feature is disabled by default and has no effect unless you explicitly enable it.
                </Text>
                <Text size="xs" render={<p className="m-0" />}>
                    By enabling this feature, you explicitly instruct us to route applicable traffic via{' '}
                    <InlineLink to="https://www.cloudflare.com">Cloudflare</InlineLink>, and understand that data
                    processed as part of this feature will be transmitted to and processed by Cloudflare.
                </Text>
            </div>
            <Card size="sm">
                <CardHeader>
                    <CardTitle>Third-party processing (Cloudflare)</CardTitle>
                </CardHeader>
                <CardContent className="flex flex-col gap-2">
                    <Text size="xs" render={<p className="m-0" />}>
                        This feature routes certain customer and customer end-user traffic through Cloudflare, a
                        third-party infrastructure provider, for the purpose of delivering the managed proxy
                        functionality. Cloudflare is listed as a{' '}
                        <InlineLink to="https://posthog.com/subprocessors">subprocessor</InlineLink> referenced in our{' '}
                        <InlineLink to="https://posthog.com/dpa">Data Processing Agreement</InlineLink> ("
                        <strong>DPA</strong>") for this purpose.
                    </Text>
                    <Text size="xs" render={<p className="m-0" />}>
                        By enabling this feature, you:
                    </Text>
                    <Text size="xs" render={<ul className="m-0 flex list-disc flex-col gap-1 pl-5" />}>
                        <li>Explicitly instruct us to route applicable data through Cloudflare for this service;</li>
                        <li>
                            Acknowledge and agree that data processed as part of this feature will be transmitted to and
                            processed by Cloudflare, and that this processing may occur using Cloudflare infrastructure
                            in multiple or dynamically assigned geographic locations as part of providing managed
                            reverse proxy functionality, in accordance with our DPA; and
                        </li>
                        <li>
                            Understand that traffic routed through this proxy is handled by Cloudflare as described in
                            our DPA.
                        </li>
                    </Text>
                </CardContent>
            </Card>
            <Card size="sm">
                <CardHeader>
                    <CardTitle>HIPAA Disclaimer</CardTitle>
                </CardHeader>
                <CardContent>
                    <Text size="xs" render={<p className="m-0" />}>
                        This feature is not HIPAA-compliant and is not intended for the processing of Protected Health
                        Information ("<strong>PHI</strong>"). Any Business Associate Agreement ("<strong>BAA</strong>")
                        you may have entered into with PostHog does not apply to this functionality. You agree not to
                        use this feature with PHI.
                    </Text>
                </CardContent>
            </Card>
            <div className="flex flex-col items-start gap-3">
                <Field orientation="horizontal" className="w-fit">
                    <Checkbox
                        id={checkboxId}
                        checked={cloudflareOptInChecked}
                        onCheckedChange={(checked) => setCloudflareOptInChecked(checked)}
                    />
                    <FieldLabel htmlFor={checkboxId}>I have read and agree to the above terms</FieldLabel>
                </Field>
                <Button
                    variant="primary"
                    onClick={onAcknowledge}
                    disabledReason={
                        restrictionReason || (!cloudflareOptInChecked ? 'You must agree to the terms' : undefined)
                    }
                >
                    Enable Managed Proxy
                </Button>
            </div>
        </div>
    )
}
