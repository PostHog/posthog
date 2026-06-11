import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { SceneExport } from 'scenes/sceneTypes'

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
        isOauthSource,
        storedCredential,
        availableSourcesLoading,
        isCredentialsFormSubmitting,
    } = useValues(sourceConnectSceneLogic)
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
                    isOauthSource || storedCredential
                        ? undefined
                        : `Enter your ${sourceLabel} credentials. They are stored encrypted and never shared with anyone — including the assistant that sent you here.`
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
                ) : isOauthSource ? (
                    <LemonBanner type="info">
                        <p className="font-semibold mb-1">{sourceLabel} connects through your browser.</p>
                        <p className="m-0 text-sm">
                            If you've just finished authorizing {sourceLabel} in this window, you're all set — return to
                            your chat and let the assistant know, and it will finish setting up the source.
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
                        <SourceFormComponent
                            sourceConfig={sourceConfig}
                            showPrefix={false}
                            showDescription={false}
                            showAccessMethodSelector={false}
                            showCdcConfig={false}
                            setSourceConnectionDetailsValue={setCredentialsFormValue}
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
