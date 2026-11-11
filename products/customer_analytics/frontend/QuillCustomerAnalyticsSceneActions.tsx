import { useActions, useValues } from 'kea'

import { Button, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { customerJourneysLogic } from './components/CustomerJourneys/customerJourneysLogic'
import { DeleteJourneyButton } from './components/CustomerJourneys/DeleteJourneyButton'
import { journeyEditorLogic } from './components/CustomerJourneys/journeyEditorLogic'
import { QuillCustomerJourneySelect } from './components/CustomerJourneys/QuillCustomerJourneySelect'
import { FeedbackButton } from './components/FeedbackButton'
import { TaskDigestButton } from './components/TaskDigest/TaskDigestButton'
import { customerAnalyticsSceneLogic } from './customerAnalyticsSceneLogic'

// Under today-rail-nav, Configure is a row in the People pane, so the header has no Configure button.
export function QuillCustomerAnalyticsSceneActions(): JSX.Element {
    const { activeTab } = useValues(customerAnalyticsSceneLogic)
    const { isEditMode, stagedNodes, isSaving } = useValues(journeyEditorLogic)
    const { saveChanges, cancelChanges } = useActions(journeyEditorLogic)
    const { activeJourney } = useValues(customerJourneysLogic)

    const accessControlDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.CustomerAnalytics,
        AccessControlLevel.Editor
    )

    return (
        <div className="flex flex-wrap items-center gap-2">
            <FeedbackButton id="customer-analytics-dashboard-feedback-button" />
            {activeTab === 'tasks' && <TaskDigestButton />}
            {isEditMode ? (
                <div className="flex flex-wrap items-center gap-2">
                    <Text size="xs" variant="muted" weight="medium" render={<span className="whitespace-nowrap" />}>
                        {stagedNodes.length} step{stagedNodes.length !== 1 ? 's' : ''} to add
                    </Text>
                    <Button variant="outline" onClick={cancelChanges}>
                        Cancel
                    </Button>
                    <Button
                        variant="primary"
                        onClick={saveChanges}
                        disabledReason={
                            accessControlDisabledReason ?? (stagedNodes.length === 0 ? 'No steps staged' : undefined)
                        }
                        loading={isSaving}
                    >
                        Save
                    </Button>
                </div>
            ) : activeTab === 'journeys' ? (
                <>
                    <QuillCustomerJourneySelect />
                    <Button
                        variant="primary"
                        render={<LinkPrimitive to={urls.customerJourneyTemplates()} />}
                        data-attr="new-journey"
                        disabledReason={accessControlDisabledReason}
                    >
                        New journey
                    </Button>
                    {activeJourney && (
                        <Button
                            variant="outline"
                            render={
                                <LinkPrimitive
                                    to={`${urls.customerJourneyEdit(activeJourney.id)}?insightId=${activeJourney.insight}`}
                                />
                            }
                            data-attr="edit-journey"
                        >
                            Edit
                        </Button>
                    )}
                    <DeleteJourneyButton />
                </>
            ) : null}
        </div>
    )
}
