import { IconPlus } from '@posthog/icons'
import { Button, Card, CardContent, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { AuthorizedDomains } from '../../scenes/settings/AuthorizedDomains'
import { IdentityVerificationSecretSection } from '../../scenes/settings/IdentityVerificationSecretSection'
import { QuillSettingsSubsection } from '../QuillSettingsSubsection/QuillSettingsSubsection'
import { WEB_AND_API_ACCESS_ANCHOR_ID } from '../WebAndApiAccessSettings/webAndApiAccessAnchor'

export function QuillWebAndApiAccessSettings({
    showAddDomainButton,
    onAddDomain,
}: {
    showAddDomainButton: boolean
    onAddDomain: () => void
}): JSX.Element {
    return (
        <div
            id={WEB_AND_API_ACCESS_ANCHOR_ID}
            className="scroll-mt-[calc(var(--scene-layout-header-height)+var(--spacing)*4)]"
        >
            <QuillSettingsSubsection
                title="Web and API access"
                description="These settings apply to the widget and the Direct API. Other channels don't use them."
            >
                <div className="flex flex-col gap-4">
                    <QuillSettingsSubsection
                        title="Allowed domains"
                        description={
                            <>
                                Specify which domains can call the conversations API (widget and direct API). Leave
                                empty to allow all domains. Wildcards supported (e.g. <code>https://*.example.com</code>
                                ).{' '}
                                <Button
                                    variant="link"
                                    size="inline"
                                    nativeButton={false}
                                    render={
                                        <LinkPrimitive
                                            to="https://posthog.com/docs/support/javascript-api"
                                            target="_blank"
                                        />
                                    }
                                >
                                    Docs
                                </Button>
                            </>
                        }
                    >
                        <Card size="sm" className="max-w-200">
                            <CardContent className="flex flex-col gap-2">
                                <AuthorizedDomains />
                                {showAddDomainButton && (
                                    <div>
                                        <Button variant="outline" onClick={onAddDomain}>
                                            <IconPlus />
                                            Add domain
                                        </Button>
                                    </div>
                                )}
                            </CardContent>
                        </Card>
                    </QuillSettingsSubsection>
                    <QuillSettingsSubsection
                        title="Identity verification"
                        description={
                            <>
                                For logged-in users, sign their distinct_id on your backend with the identity
                                verification secret so tickets persist across browsers and devices without email
                                recovery.{' '}
                                <Button
                                    variant="link"
                                    size="inline"
                                    nativeButton={false}
                                    render={
                                        <LinkPrimitive
                                            to="https://posthog.com/docs/support/javascript-api#user-identification"
                                            target="_blank"
                                        />
                                    }
                                >
                                    Read the docs
                                </Button>
                            </>
                        }
                    >
                        <Card size="sm" className="max-w-200">
                            <CardContent className="flex flex-col gap-2">
                                <Text size="xs" render={<p className="m-0" />}>
                                    Compute an HMAC-SHA256 of the user's <code>distinct_id</code> using the identity
                                    verification secret below (server-side) and pass both values to{' '}
                                    <code>posthog.init()</code>:
                                </Text>
                                <pre data-quill className="m-0 overflow-x-auto rounded-md bg-muted p-3 text-xs">
                                    {`posthog.init('<ph_project_api_key>', {
    identity_distinct_id: 'user_123',
    identity_hash: 'a1b2c3d4e5f6...',
})`}
                                </pre>
                                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                                    Without identity verification, tickets are scoped to a browser session and users
                                    must recover them by email when switching devices.
                                </Text>
                            </CardContent>
                        </Card>
                    </QuillSettingsSubsection>
                    <IdentityVerificationSecretSection />
                </div>
            </QuillSettingsSubsection>
        </div>
    )
}
