import { useValues } from 'kea'

import {
    Button,
    Callout,
    CalloutActions,
    CalloutContent,
    CalloutDescription,
    CalloutIcon,
    Field,
    FieldLabel,
} from '@posthog/quill'

import { eventsWithMoveNotice, moveAnnouncementUrl } from 'lib/components/TaxonomicFilter/utils/hiddenEvents'
import { FEATURE_FLAGS } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { getFeatureFlagPayload } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'

import { ActionStepType } from '~/types'

import { EventName } from './EventName'

/** The event picker of an "Other events" match group. */
export function QuillActionStepEventName({
    step,
    sendStep,
    disabledReason,
}: {
    step: ActionStepType
    sendStep: (step: ActionStepType) => void
    disabledReason?: string
}): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const moveNoticeEvents = eventsWithMoveNotice(
        currentTeam?.flag_evaluations_mode,
        useFeatureFlag('FLAG_CALLED_MOVE_NOTICES')
    )
    const announcementUrl = moveAnnouncementUrl(getFeatureFlagPayload(FEATURE_FLAGS.FLAG_CALLED_MOVE_NOTICES))
    const showMoveNotice = typeof step.event === 'string' && moveNoticeEvents.includes(step.event)

    return (
        <Field>
            <FieldLabel>Event name</FieldLabel>
            <EventName
                value={step.event ?? null}
                onChange={(value) => sendStep({ ...step, event: value })}
                placeholder="All events"
                allEventsOption="explicit"
                disabled={!!disabledReason}
                fullWidth
            />
            {showMoveNotice && (
                <Callout tone="warning">
                    <CalloutIcon />
                    <CalloutContent>
                        <CalloutDescription>
                            Feature flag called is moving out of the events table. Once PostHog starts reading flag
                            calls from the new table, you can't add new steps on this event. To see how a flag is used,
                            open the flag and check its Usage tab.
                        </CalloutDescription>
                    </CalloutContent>
                    {announcementUrl && (
                        <CalloutActions>
                            <Button variant="outline" render={<LinkPrimitive to={announcementUrl} target="_blank" />}>
                                Learn more
                            </Button>
                        </CalloutActions>
                    )}
                </Callout>
            )}
            <div>
                <Button
                    variant="link"
                    size="inline"
                    render={<LinkPrimitive to="https://posthog.com/docs/libraries" target="_blank" />}
                >
                    See documentation
                </Button>
            </div>
        </Field>
    )
}
