import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import React from 'react'

import { IconQuestion } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonSkeleton, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { SourceFormComponent } from '../../shared/components/forms/SourceForm'
import { SourceIcon } from '../../shared/components/SourceIcon'
import { sourceConnectSceneLogic } from './sourceConnectSceneLogic'

export const scene: SceneExport = {
    component: SourceConnectScene,
    logic: sourceConnectSceneLogic,
}

export function SourceConnectScene(): JSX.Element {
    const {
        kind,
        sourceConfig,
        storedCredential,
        availableSourcesLoading,
        isCredentialsFormSubmitting,
        migrationParams,
        migrationPrefillLoading,
        migrationPrefill,
        prefillConfirmed,
    } = useValues(sourceConnectSceneLogic)
    const { setCredentialsFormValue } = useActions(sourceConnectSceneLogic)

    // Wait for the migration prefill, so it never lands on top of what the user typed.
    if (availableSourcesLoading || migrationPrefillLoading) {
        return <LemonSkeleton />
    }

    if (!sourceConfig) {
        return (
            <SceneContent>
                <LemonBanner type="error" action={{ children: 'Browse sources', to: urls.dataWarehouseSourceNew() }}>
                    {kind
                        ? "This link names a source we don't support."
                        : "This link doesn't say which source to connect."}{' '}
                    Choose your source from the full list to set it up.
                </LemonBanner>
            </SceneContent>
        )
    }

    const sourceLabel = sourceConfig.label ?? sourceConfig.name

    return (
        <SceneContent>
            <SceneTitleSection
                name={`Connect ${sourceLabel}`}
                resourceType={{ type: 'data_pipeline' }}
                description={
                    storedCredential
                        ? undefined
                        : `Connect your ${sourceLabel} account or enter its credentials. Everything you submit is stored encrypted, kept only until the source is created (at most 24 hours), and never shared with anyone — including the assistant that sent you here.`
                }
            />
            <div className="max-w-200">
                {storedCredential ? (
                    <LemonBanner type="success">
                        <p className="font-semibold mb-1">{sourceLabel} credentials saved. You can close this tab.</p>
                        <p className="m-0 text-sm">
                            The source doesn't exist yet, so it won't show in your sources list. Return to your chat and
                            let the assistant know you're done, and it will finish the setup. Credential id:{' '}
                            <code>{storedCredential.credential_id}</code>.
                        </p>
                    </LemonBanner>
                ) : (
                    <Form
                        logic={sourceConnectSceneLogic}
                        formKey="credentialsForm"
                        enableFormOnSubmit
                        className="space-y-4"
                    >
                        <div className="flex items-center gap-2">
                            <SourceIcon type={sourceConfig.name} size="small" />
                            <span className="font-semibold">{sourceLabel}</span>
                        </div>
                        {(sourceConfig.permissionsCaption || sourceConfig.docsUrl) && (
                            <div className="flex flex-row items-center gap-1">
                                {sourceConfig.permissionsCaption && (
                                    <Tooltip
                                        title={
                                            <LemonMarkdown className="text-sm">
                                                {sourceConfig.permissionsCaption}
                                            </LemonMarkdown>
                                        }
                                        interactive
                                    >
                                        <LemonTag type="muted" size="small">
                                            Permissions required <IconQuestion />
                                        </LemonTag>
                                    </Tooltip>
                                )}
                                {sourceConfig.permissionsCaption && sourceConfig.docsUrl && <span>&nbsp;|&nbsp;</span>}
                                {sourceConfig.docsUrl && (
                                    <Link to={sourceConfig.docsUrl} target="_blank">
                                        View docs
                                    </Link>
                                )}
                            </div>
                        )}
                        {migrationPrefill && <MigrationPrefillConfirm sourceName={sourceConfig.name} />}
                        <SourceFormComponent
                            sourceConfig={sourceConfig}
                            lockedValues={migrationPrefill ?? undefined}
                            showPrefix={false}
                            showDescription={false}
                            showAccessMethodSelector={false}
                            showCdcConfig={false}
                            setSourceConnectionDetailsValue={setCredentialsFormValue}
                            oauthRedirectUrl={
                                urls.dataWarehouseSourceConnect(sourceConfig.name) +
                                (migrationParams
                                    ? `&migration_id=${encodeURIComponent(migrationParams.migrationId)}&migration_item_id=${encodeURIComponent(migrationParams.itemId)}`
                                    : '')
                            }
                        />
                        <LemonButton
                            type="primary"
                            htmlType="submit"
                            loading={isCredentialsFormSubmitting}
                            disabledReason={
                                isCredentialsFormSubmitting
                                    ? 'Saving…'
                                    : migrationPrefill && !prefillConfirmed
                                      ? 'Confirm the server above first'
                                      : undefined
                            }
                        >
                            Save credentials
                        </LemonButton>
                    </Form>
                )}
            </div>
        </SceneContent>
    )
}

function MigrationPrefillConfirm({ sourceName }: { sourceName: string }): JSX.Element {
    const { migrationCreator, prefilledFieldRows, prefillConfirmed } = useValues(sourceConnectSceneLogic)
    const { setPrefillConfirmed } = useActions(sourceConnectSceneLogic)

    return (
        <LemonBanner type="warning">
            <p className="font-semibold mb-1">Check where your credentials go</p>
            <p className="m-0 mb-2 text-sm">
                {migrationCreator
                    ? `${migrationCreator.first_name || migrationCreator.email} (${migrationCreator.email}) prepared this connection.`
                    : 'A migration prepared this connection.'}{' '}
                PostHog checks the credentials you enter against this server, so only continue if you trust it.
            </p>
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 m-0 mb-2 text-sm">
                {prefilledFieldRows.map(({ label, value }) => (
                    <React.Fragment key={label}>
                        <dt className="text-secondary">{label}</dt>
                        <dd className="m-0 font-mono break-all">{value}</dd>
                    </React.Fragment>
                ))}
            </dl>
            <div className="flex flex-wrap items-center justify-between gap-2">
                <LemonCheckbox
                    checked={prefillConfirmed}
                    onChange={setPrefillConfirmed}
                    label="I confirm this is the right server"
                    data-attr="source-connect-confirm-prefill"
                />
                <Link to={urls.dataWarehouseSourceConnect(sourceName)} data-attr="source-connect-new-source-instead">
                    Set up a new source instead
                </Link>
            </div>
        </LemonBanner>
    )
}

export default SourceConnectScene
