import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconQuestion } from '@posthog/icons'
import { LemonButton, LemonSkeleton, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

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
    const { kind, sourceConfig, storedCredential, availableSourcesLoading, isCredentialsFormSubmitting } =
        useValues(sourceConnectSceneLogic)
    const { setCredentialsFormValue } = useActions(sourceConnectSceneLogic)

    if (availableSourcesLoading) {
        return <LemonSkeleton />
    }

    if (!sourceConfig) {
        return (
            <SceneContent>
                <LemonBanner type="error">
                    {kind ? `Unknown source type '${kind}'.` : 'No source type specified.'} Check the link you were
                    given and try again.
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
                        <p className="font-semibold mb-1">{sourceLabel} credentials saved — you can close this tab.</p>
                        <p className="m-0 text-sm">
                            Return to your chat and let the assistant know you're done; it will finish setting up the
                            source. Credential id: <code>{storedCredential.credential_id}</code>.
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
                        <SourceFormComponent
                            sourceConfig={sourceConfig}
                            showPrefix={false}
                            showDescription={false}
                            showAccessMethodSelector={false}
                            showCdcConfig={false}
                            setSourceConnectionDetailsValue={setCredentialsFormValue}
                            oauthRedirectUrl={urls.dataWarehouseSourceConnect(sourceConfig.name)}
                        />
                        <LemonButton
                            type="primary"
                            htmlType="submit"
                            loading={isCredentialsFormSubmitting}
                            disabledReason={isCredentialsFormSubmitting ? 'Saving…' : undefined}
                        >
                            Save credentials
                        </LemonButton>
                    </Form>
                )}
            </div>
        </SceneContent>
    )
}

export default SourceConnectScene
