import { useActions, useValues } from 'kea'

import { IconPlus } from '@posthog/icons'
import { LemonButton, LemonCard, Link } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { AuthorizedDomains } from '../../scenes/settings/AuthorizedDomains'
import { IdentityVerificationSecretSection } from '../../scenes/settings/IdentityVerificationSecretSection'
import { supportSettingsLogic } from '../../scenes/settings/supportSettingsLogic'
import { QuillWebAndApiAccessSettings } from '../QuillWebAndApiAccessSettings/QuillWebAndApiAccessSettings'
import { WEB_AND_API_ACCESS_ANCHOR_ID } from './webAndApiAccessAnchor'

export function WebAndApiAccessSettings(): JSX.Element {
    const { isAddingDomain, editingDomainIndex } = useValues(supportSettingsLogic)
    const { setIsAddingDomain } = useActions(supportSettingsLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const showAddDomainButton = !isAddingDomain && editingDomainIndex === null

    if (todayRailNav) {
        return (
            <QuillWebAndApiAccessSettings
                showAddDomainButton={showAddDomainButton}
                onAddDomain={() => setIsAddingDomain(true)}
            />
        )
    }

    return (
        <div
            id={WEB_AND_API_ACCESS_ANCHOR_ID}
            className="scroll-mt-[calc(var(--scene-layout-header-height)+var(--spacing)*4)]"
        >
            <SceneSection
                title="Web and API access"
                className="my-8"
                description="These settings apply to the widget and the Direct API. Other channels don't use them."
            >
                <SceneSection
                    title="Allowed domains"
                    titleSize="sm"
                    description={
                        <>
                            Specify which domains can call the conversations API (widget and direct API). Leave empty to
                            allow all domains. Wildcards supported (e.g. <code>https://*.example.com</code>
                            ).{' '}
                            <Link to="https://posthog.com/docs/support/javascript-api" target="_blank">
                                Docs
                            </Link>
                        </>
                    }
                >
                    <LemonCard hoverEffect={false} className="flex flex-col gap-y-2 max-w-[800px] px-4 py-3">
                        <AuthorizedDomains />
                        {showAddDomainButton && (
                            <LemonButton
                                onClick={() => setIsAddingDomain(true)}
                                type="secondary"
                                icon={<IconPlus />}
                                size="small"
                                className="mt-2 self-start"
                            >
                                Add domain
                            </LemonButton>
                        )}
                    </LemonCard>
                </SceneSection>
                <SceneSection
                    title="Identity verification"
                    titleSize="sm"
                    className="mt-4"
                    description={
                        <>
                            For logged-in users, sign their distinct_id on your backend with the identity verification
                            secret so tickets persist across browsers and devices without email recovery.{' '}
                            <Link
                                to="https://posthog.com/docs/support/javascript-api#user-identification"
                                target="_blank"
                                targetBlankIcon
                            >
                                Read the docs
                            </Link>
                        </>
                    }
                >
                    <LemonCard hoverEffect={false} className="max-w-[800px] px-4 py-3">
                        <p className="mb-2">
                            Compute an HMAC-SHA256 of the user's <code>distinct_id</code> using the identity
                            verification secret below (server-side) and pass both values to <code>posthog.init()</code>:
                        </p>
                        <pre className="bg-surface-secondary rounded p-3 text-xs overflow-x-auto mb-2">
                            {`posthog.init('<ph_project_api_key>', {
    identity_distinct_id: 'user_123',
    identity_hash: 'a1b2c3d4e5f6...',
})`}
                        </pre>
                        <p className="mb-0 text-xs text-muted-alt">
                            Without identity verification, tickets are scoped to a browser session and users must
                            recover them by email when switching devices.
                        </p>
                    </LemonCard>
                </SceneSection>
                <div className="mt-4">
                    <IdentityVerificationSecretSection />
                </div>
            </SceneSection>
        </div>
    )
}
