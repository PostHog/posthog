import { router } from 'kea-router'

import { IconSend } from '@posthog/icons'

import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'

import { SurveyEventName } from '~/types'

import { captureMessageAudienceClicked } from 'products/workflows/frontend/MessageAudience/messageAudience'
import { draftMessage } from 'products/workflows/frontend/MessageAudience/messageDrafts'
import {
    type WorkflowTriggerConfig,
    urlForNewWorkflowWithTrigger,
} from 'products/workflows/frontend/Workflows/workflowTriggerPrefill'

// pinned: reported as the click event's source, so renaming it splits the entry point's history
const SOURCE = 'survey'

// Keep in sync with the survey trigger in the workflow editor, which only recognizes this exact shape.
function surveyFollowUpTrigger(surveyId: string): WorkflowTriggerConfig {
    return {
        type: 'event',
        filters: {
            events: [{ id: SurveyEventName.SENT, type: 'events', name: 'Survey sent' }],
            properties: [{ key: '$survey_id', value: surveyId, operator: 'exact', type: 'event' }],
            filter_test_accounts: false,
        },
    }
}

export function SurveyFollowUpWorkflowButton({ surveyId }: { surveyId: string }): JSX.Element {
    return (
        <ButtonPrimitive
            menuItem
            tooltip="Open a workflow that emails each person who responds to this survey"
            onClick={() => {
                captureMessageAudienceClicked(SOURCE, 'workflow')
                router.actions.push(
                    urlForNewWorkflowWithTrigger(
                        surveyFollowUpTrigger(surveyId),
                        SOURCE,
                        draftMessage({ kind: 'survey_responded' }),
                        { source: 'survey', source_id: surveyId }
                    )
                )
            }}
            data-attr="survey-start-follow-up-workflow"
        >
            <IconSend />
            Email everyone who responds
        </ButtonPrimitive>
    )
}
