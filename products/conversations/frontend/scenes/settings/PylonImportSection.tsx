import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonCard, LemonInput, LemonSelect } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { FEATURE_FLAGS, OrganizationMembershipLevel } from 'lib/constants'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { ImportStatusHeader } from '../../components/ImportStatusHeader/ImportStatusHeader'
import { pylonImportLogic } from './pylonImportLogic'

function startDisabledReason(isImportRunning: boolean, apiToken: string): string | undefined {
    if (isImportRunning) {
        return 'Import already running'
    }
    return apiToken.trim() ? undefined : 'Enter an API token'
}

export function PylonImportSection(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    if (!featureFlags[FEATURE_FLAGS.PRODUCT_SUPPORT_PYLON_IMPORT]) {
        return null
    }
    return (
        <SceneSection
            title="Pylon import"
            description="Import historical Pylon issues and their message threads into Support as tickets. Issues you already imported are skipped when you run it again. Pylon limits how fast issues can be read, so a large workspace can take several hours."
        >
            <LemonCard hoverEffect={false} className="flex flex-col gap-y-3 max-w-[800px] px-4 py-3">
                <PylonImportForm />
            </LemonCard>
        </SceneSection>
    )
}

function PylonImportForm(): JSX.Element {
    const {
        apiToken,
        emailChannelId,
        emailConfigs,
        importJob,
        importJobLoading,
        isImportRunning,
        importProgressLabel,
    } = useValues(pylonImportLogic)
    const { setApiToken, setEmailChannelId, submitImport } = useActions(pylonImportLogic)
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
                    Imported {importJob.imported_issues.toLocaleString()} issues (
                    {importJob.skipped_issues.toLocaleString()} skipped, {importJob.failed_issues.toLocaleString()}{' '}
                    failed).
                </p>
            ) : null}

            <LemonField.Pure
                label="API token"
                info="A Pylon admin can create one under Settings > Integrations & dev > API tokens. The token's role must be able to read issues, messages, and contacts. US and EU workspaces both work, and the region is detected from the token."
            >
                <LemonInput
                    type="password"
                    placeholder={
                        importJob?.has_credentials
                            ? 'Configured. Enter it again to start a new import.'
                            : 'Pylon API token'
                    }
                    value={apiToken}
                    onChange={setApiToken}
                    disabled={isImportRunning}
                />
            </LemonField.Pure>
            <LemonField.Pure
                label="Reply inbox"
                info="Imported tickets are attached to this support inbox so agents can reply to customers by email. An issue sent to another support address that is connected here keeps that inbox."
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
                    disabledReason={adminRestrictionReason || startDisabledReason(isImportRunning, apiToken)}
                >
                    Start import
                </LemonButton>
            </div>
        </div>
    )
}
