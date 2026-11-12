import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, Spinner } from '@posthog/lemon-ui'
import { Button } from '@posthog/quill'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { NotFound } from 'lib/components/NotFound'
import { FEATURE_FLAGS } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { PlatformAlertConfigurationDetails } from './PlatformAlertConfigurationDetails'
import { PlatformAlertCustomSnoozeModal } from './PlatformAlertCustomSnoozeModal'
import { SOURCE_KINDS, describeOverflow, describeOverflowDetail, sourceAlertUrl } from './platformAlertFormat'
import { PlatformAlertGroupsTable } from './PlatformAlertGroupsTable'
import { PlatformAlertLogicProps, platformAlertLogic } from './platformAlertLogic'

export const scene: SceneExport = {
    component: PlatformAlertScene,
    logic: platformAlertLogic,
    paramsToProps: ({ params: { id } }): PlatformAlertLogicProps => ({ id }),
}

export function PlatformAlertScene(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { configuration, configurationLoading, configurationError, canSnoozeGroups } = useValues(platformAlertLogic)
    const { loadConfiguration } = useActions(platformAlertLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (!featureFlags[FEATURE_FLAGS.PLATFORM_ALERTS]) {
        return <NotFound object="page" />
    }

    // A reload of an alert already on screen keeps the page, so a stale-group refresh does not blank it.
    if (configurationError || !configuration) {
        return (
            <SceneContent>
                <SceneTitleSection name={configurationLoading ? '' : 'Alert'} resourceType={{ type: 'inbox' }} />
                {configurationLoading || !configurationError ? (
                    <Spinner />
                ) : (
                    <LemonBanner
                        type="error"
                        action={{
                            children: 'Retry',
                            onClick: () => loadConfiguration(),
                            'data-attr': 'platform-alert-retry',
                        }}
                    >
                        Couldn't load this alert. It may have been deleted, or you may not have access to its source.
                        Try again, or go back to the alert list.
                    </LemonBanner>
                )}
            </SceneContent>
        )
    }

    const sourceLabel = SOURCE_KINDS[configuration.source_kind].label
    const sourceUrl = sourceAlertUrl(configuration)
    const overflow = describeOverflow(configuration)

    return (
        <SceneContent>
            <SceneTitleSection
                name={configuration.name}
                description={`${sourceLabel} alert`}
                resourceType={{ type: 'inbox' }}
                actions={
                    sourceUrl ? (
                        todayRailNav ? (
                            <Button
                                variant="outline"
                                render={<LinkPrimitive to={sourceUrl} />}
                                data-attr="platform-alert-open-source"
                            >
                                Open in {sourceLabel}
                            </Button>
                        ) : (
                            <LemonButton
                                type="secondary"
                                size="small"
                                to={sourceUrl}
                                data-attr="platform-alert-open-source"
                            >
                                Open in {sourceLabel}
                            </LemonButton>
                        )
                    ) : undefined
                }
            />
            <SceneSection title="Configuration">
                <PlatformAlertConfigurationDetails configuration={configuration} />
            </SceneSection>
            <SceneSection
                title="Groups"
                description={
                    canSnoozeGroups
                        ? 'Runtime state for each result group. Snooze a group to hold its notifications. It keeps being checked, and a firing group stays firing.'
                        : 'Runtime state for each result group. An alert that does not group results has one row.'
                }
            >
                {overflow && (
                    <LemonBanner type="warning">
                        <p className="m-0 font-semibold">{overflow}</p>
                        <p className="m-0">{describeOverflowDetail(configuration)}</p>
                    </LemonBanner>
                )}
                <PlatformAlertGroupsTable
                    alerts={configuration.alerts}
                    groupingKeys={configuration.grouping.keys ?? []}
                />
                <PlatformAlertCustomSnoozeModal />
            </SceneSection>
            <SceneSection title="Source settings">
                <CodeSnippet language={Language.JSON} wrap>
                    {JSON.stringify(configuration.source_config, null, 2)}
                </CodeSnippet>
            </SceneSection>
        </SceneContent>
    )
}
