import { useActions, useValues } from 'kea'

import { IconPlusSmall } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'

import { CloudAgentsSceneShell } from '../components/CloudAgentsSceneShell'
import { LoadErrorBanner } from '../components/LoadErrorBanner'
import { PresetsTable } from '../components/PresetsTable'
import { cloudAgentPresetsLogic } from '../logics/cloudAgentPresetsLogic'
import { CloudAgentsSceneLogicProps, cloudAgentsSceneLogic } from '../logics/cloudAgentsSceneLogic'

export const scene: SceneExport<CloudAgentsSceneLogicProps> = {
    component: CloudAgentPresetsScene,
    logic: cloudAgentsSceneLogic,
    paramsToProps: () => ({ scene: 'presets' }),
    productKey: ProductKey.CLOUD_AGENTS,
}

export function CloudAgentPresetsScene(): JSX.Element {
    const { presets, presetsLoadFailed, presetsLoading } = useValues(cloudAgentPresetsLogic)
    const { loadPresets } = useActions(cloudAgentPresetsLogic)

    return (
        <CloudAgentsSceneShell
            activeTab="presets"
            actions={
                <LemonButton
                    type="primary"
                    size="small"
                    icon={<IconPlusSmall />}
                    to={urls.cloudAgentPreset('new')}
                    data-attr="cloud-agents-new-preset"
                >
                    New preset
                </LemonButton>
            }
        >
            {presets === null && presetsLoadFailed ? (
                <LoadErrorBanner what="the presets" onRetry={loadPresets} retrying={presetsLoading} />
            ) : (
                <PresetsTable />
            )}
        </CloudAgentsSceneShell>
    )
}
