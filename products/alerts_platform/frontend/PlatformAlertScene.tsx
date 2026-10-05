import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, Spinner } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { NotFound } from 'lib/components/NotFound'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { PlatformAlertConfigurationApi, PlatformAlertConfigurationSourceKindEnumApi } from './generated/api.schemas'
import { PlatformAlertConfigurationDetails } from './PlatformAlertConfigurationDetails'
import { SOURCE_KIND_LABELS } from './platformAlertFormat'
import { PlatformAlertGroupsTable } from './PlatformAlertGroupsTable'
import { PlatformAlertLogicProps, platformAlertLogic } from './platformAlertLogic'

export const scene: SceneExport = {
    component: PlatformAlertScene,
    logic: platformAlertLogic,
    paramsToProps: ({ params: { id } }): PlatformAlertLogicProps => ({ id }),
}

function sourceAlertUrl(configuration: PlatformAlertConfigurationApi): string | null {
    if (
        configuration.source_kind === PlatformAlertConfigurationSourceKindEnumApi.Logs &&
        configuration.legacy_configuration_id
    ) {
        return urls.logsAlertDetail(configuration.legacy_configuration_id)
    }
    return null
}

export function PlatformAlertScene(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { configuration, configurationLoading, configurationError } = useValues(platformAlertLogic)
    const { loadConfiguration } = useActions(platformAlertLogic)

    if (!featureFlags[FEATURE_FLAGS.PLATFORM_ALERTS]) {
        return <NotFound object="page" />
    }

    const sourceLabel = configuration
        ? (SOURCE_KIND_LABELS[configuration.source_kind] ?? configuration.source_kind)
        : null
    const sourceUrl = configuration ? sourceAlertUrl(configuration) : null

    return (
        <SceneContent>
            <SceneTitleSection
                name={configuration?.name ?? (configurationLoading ? '' : 'Alert')}
                description={sourceLabel ? `${sourceLabel} alert` : undefined}
                resourceType={{ type: 'inbox' }}
                actions={
                    sourceUrl ? (
                        <LemonButton
                            type="secondary"
                            size="small"
                            to={sourceUrl}
                            data-attr="platform-alert-open-source"
                        >
                            Open in {sourceLabel}
                        </LemonButton>
                    ) : undefined
                }
            />
            {configurationLoading && !configuration ? (
                <Spinner />
            ) : configurationError && !configuration ? (
                <LemonBanner
                    type="error"
                    action={{
                        children: 'Retry',
                        onClick: () => loadConfiguration(),
                        'data-attr': 'platform-alert-retry',
                    }}
                >
                    Couldn't load this alert. It may have been deleted, or you may not have access to its source. Try
                    again, or go back to the alert list.
                </LemonBanner>
            ) : configuration ? (
                <>
                    <SceneSection title="Configuration">
                        <PlatformAlertConfigurationDetails configuration={configuration} />
                    </SceneSection>
                    <SceneSection
                        title="Groups"
                        description="Runtime state for each result group. An alert that does not group results has one row."
                    >
                        <PlatformAlertGroupsTable alerts={configuration.alerts} />
                    </SceneSection>
                    <SceneSection title="Source settings">
                        <CodeSnippet language={Language.JSON} wrap>
                            {JSON.stringify(configuration.source_config, null, 2)}
                        </CodeSnippet>
                    </SceneSection>
                </>
            ) : null}
        </SceneContent>
    )
}
