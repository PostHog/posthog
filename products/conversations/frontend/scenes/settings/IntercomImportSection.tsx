import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonCard, LemonInput, LemonSelect } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { FEATURE_FLAGS, OrganizationMembershipLevel } from 'lib/constants'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { ImportStatusHeader } from '../../components/ImportStatusHeader/ImportStatusHeader'
import { intercomImportLogic, IntercomRegion } from './intercomImportLogic'

const REGION_OPTIONS: { label: string; value: IntercomRegion }[] = [
    { label: 'United States', value: 'us' },
    { label: 'Europe', value: 'eu' },
    { label: 'Australia', value: 'au' },
]

function startDisabledReason(isImportRunning: boolean, accessToken: string): string | undefined {
    if (isImportRunning) {
        return 'Import already running'
    }
    return accessToken.trim() ? undefined : 'Enter an access token'
}

export function IntercomImportSection(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    if (!featureFlags[FEATURE_FLAGS.PRODUCT_SUPPORT_INTERCOM_IMPORT]) {
        return null
    }
    return (
        <SceneSection
            title="Intercom import"
            description="Import historical Intercom conversations and their message threads into Support as tickets. Conversations you already imported are skipped when you run it again."
        >
            <LemonCard hoverEffect={false} className="flex flex-col gap-y-3 max-w-[800px] px-4 py-3">
                <IntercomImportForm />
            </LemonCard>
        </SceneSection>
    )
}

function IntercomImportForm(): JSX.Element {
    const {
        region,
        accessToken,
        emailChannelId,
        emailConfigs,
        importJob,
        importJobLoading,
        isImportRunning,
        importProgressLabel,
    } = useValues(intercomImportLogic)
    const { setRegion, setAccessToken, setEmailChannelId, submitImport } = useActions(intercomImportLogic)
    const adminRestrictionReason = useRestrictedArea({
        scope: RestrictionScope.Organization,
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
    })

    return (
        <div className="flex flex-col gap-y-3">
            <ImportStatusHeader
                status={importJob?.status}
                progressLabel={importProgressLabel}
                latestError={importJob?.latest_error}
            />

            {importJob?.status === 'completed' ? (
                <p className="text-xs text-muted-alt m-0">
                    Imported {importJob.imported_conversations.toLocaleString()} conversations (
                    {importJob.skipped_conversations.toLocaleString()} skipped,{' '}
                    {importJob.failed_conversations.toLocaleString()} failed).
                </p>
            ) : null}

            <LemonField.Pure label="Workspace region" info="Where your Intercom workspace is hosted.">
                <LemonSelect<IntercomRegion>
                    value={region}
                    onChange={setRegion}
                    disabled={isImportRunning}
                    options={REGION_OPTIONS}
                />
            </LemonField.Pure>
            <LemonField.Pure
                label="Access token"
                info="Create an app in Intercom's Developer Hub and copy its access token from Configure > Authentication. The import can only read conversations that the teammate who installed the app has access to."
            >
                <LemonInput
                    type="password"
                    placeholder={
                        importJob?.has_credentials
                            ? 'Configured. Enter it again to start a new import.'
                            : 'Intercom access token'
                    }
                    value={accessToken}
                    onChange={setAccessToken}
                    disabled={isImportRunning}
                />
            </LemonField.Pure>
            <LemonField.Pure
                label="Reply inbox"
                info="Imported tickets are attached to this support inbox so agents can reply to customers by email."
            >
                <LemonSelect<string | null>
                    value={emailChannelId}
                    onChange={setEmailChannelId}
                    disabled={isImportRunning}
                    placeholder="No inbox"
                    options={[
                        { label: 'No inbox', value: null },
                        ...emailConfigs.map((config) => ({ label: config.from_email, value: config.id })),
                    ]}
                />
            </LemonField.Pure>
            {emailChannelId === null && !isImportRunning && (
                <LemonBanner type="warning">
                    Without a reply inbox, imported tickets have no email channel. Agents can read them but can't reply
                    to those customers by email.
                </LemonBanner>
            )}
            <div>
                <LemonButton
                    type="primary"
                    onClick={submitImport}
                    loading={importJobLoading}
                    disabledReason={adminRestrictionReason || startDisabledReason(isImportRunning, accessToken)}
                >
                    Start import
                </LemonButton>
            </div>
        </div>
    )
}
