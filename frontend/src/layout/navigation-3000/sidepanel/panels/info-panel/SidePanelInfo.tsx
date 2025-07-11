import { capitalizeFirstLetter } from 'lib/utils'
import { SidePanelPaneHeader } from '../../components/SidePanelPaneHeader'
import { useActions, useValues } from 'kea'
import { sidePanelInfoLogic, SidePanelInfoTab } from './sidePanelInfoLogic'
import { LemonTabs, LemonTag, Tooltip } from '@posthog/lemon-ui'
import { sidePanelContextLogic } from '../sidePanelContextLogic'
import { AccessControlObject } from '../access_control/AccessControlObject'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { sidePanelDiscussionLogic } from '../discussion/sidePanelDiscussionLogic'
import { DiscussionContent } from '../discussion/SidePanelDiscussion'
import { WarningHog } from 'lib/components/hedgehogs'
import { humanizeScope } from 'lib/components/ActivityLog/humanizeActivity'

export const SidePanelInfo = (): JSX.Element => {
    const { registerSidePanelInfoContentElement, setActiveTab } = useActions(sidePanelInfoLogic)
    const { sceneHasSidePanel, activeTab, sidePanelInfoEnabledTabs } = useValues(sidePanelInfoLogic)
    const { sceneSidePanelContext } = useValues(sidePanelContextLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { commentsLogicProps } = useValues(sidePanelDiscussionLogic)
    const { scope, item_id } = commentsLogicProps ?? {}

    // Render the corresponding component based on active tab
    const renderTabContent = (): JSX.Element => {
        switch (activeTab) {
            case SidePanelInfoTab.AccessControl:
                return sceneSidePanelContext.access_control_resource &&
                    sceneSidePanelContext.access_control_resource_id ? (
                    <AccessControlObject
                        resource={sceneSidePanelContext.access_control_resource}
                        resource_id={sceneSidePanelContext.access_control_resource_id}
                        title="Object permissions"
                        description="Use object permissions to assign access for individuals and roles."
                    />
                ) : (
                    <p>Not supported</p>
                )
            case SidePanelInfoTab.Discussion:
                return featureFlags[FEATURE_FLAGS.DISCUSSIONS] ? (
                    commentsLogicProps && !commentsLogicProps.disabled ? (
                        <>
                            <div className="flex deprecated-space-x-2">
                                <span>
                                    Discussion{' '}
                                    {scope ? (
                                        <span className="font-normal text-secondary">
                                            about {item_id ? 'this' : ''} {humanizeScope(scope, !!item_id)}
                                        </span>
                                    ) : null}
                                </span>
                                <Tooltip title="This is a feature we are experimenting with! We'd love to get your feedback on it and whether this is something useful for working with PostHog.">
                                    <LemonTag type="completion">Experimental</LemonTag>
                                </Tooltip>
                            </div>
                            <DiscussionContent logicProps={commentsLogicProps} />
                        </>
                    ) : (
                        <div className="mx-auto p-8 max-w-160 mt-8 deprecated-space-y-4">
                            <div className="max-w-80 mx-auto">
                                <WarningHog className="w-full h-full" />
                            </div>
                            <h2>Discussions aren't supported here yet...</h2>
                            <p>
                                This a beta feature that is currently only available when viewing things like an
                                Insight, Dashboard or Notebook.
                            </p>
                        </div>
                    )
                ) : (
                    <p>Not supported</p>
                )
            default:
                return sceneHasSidePanel ? <div ref={registerSidePanelInfoContentElement} /> : <p>Not supported yet</p>
        }
    }

    return (
        <div className="flex flex-col overflow-hidden">
            <SidePanelPaneHeader title={`${capitalizeFirstLetter('context')}`} />
            <div className="flex-1 px-3 pt-2 pb-3 overflow-y-auto overflow-x-hidden">
                <div className="shrink-0">
                    <LemonTabs
                        activeKey={activeTab as SidePanelInfoTab}
                        onChange={(key) => setActiveTab(key)}
                        tabs={sidePanelInfoEnabledTabs.map((tab) => ({
                            key: tab,
                            label: capitalizeFirstLetter(tab),
                        }))}
                    />
                </div>
                {renderTabContent()}
            </div>
        </div>
    )
}
