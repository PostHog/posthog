import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconBolt, IconCodeInsert, IconPlus, IconX } from '@posthog/icons'
import { Button, Card, Input, Text } from '@posthog/quill'

import { StepLayout } from '../components/StepLayout'
import { guidedOnboardingLogic } from '../guidedOnboardingLogic'

export function EventsStep(): JSX.Element {
    const { trackedEvents, focus } = useValues(guidedOnboardingLogic)
    const { addTrackedEvent, removeTrackedEvent, next } = useActions(guidedOnboardingLogic)
    const [newEvent, setNewEvent] = useState('')
    const add = (): void => {
        addTrackedEvent(newEvent)
        setNewEvent('')
    }

    return (
        <StepLayout
            title="Confirm the events to track"
            description={
                focus?.custom
                    ? 'Add the events that measure your goal.'
                    : "These events measure your goal. Remove any you don't need, and add your own."
            }
            primary={
                <Button variant="primary" onClick={next} data-attr="guided-onboarding-events-continue">
                    Continue
                </Button>
            }
        >
            <div className="flex flex-col gap-2" data-attr="guided-onboarding-events-list">
                {trackedEvents.map((event) => {
                    const automatic = event.startsWith('$')
                    return (
                        <Card key={event} size="sm" className="flex-row items-center gap-3 px-3 py-2">
                            <span className="flex size-7 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground">
                                {automatic ? <IconBolt /> : <IconCodeInsert />}
                            </span>
                            <span className="flex min-w-0 flex-1 flex-col">
                                <Text size="sm" className="truncate font-mono">
                                    {event}
                                </Text>
                                <Text size="xs" variant="muted">
                                    {automatic
                                        ? 'PostHog captures this automatically'
                                        : 'Custom event, added to your code'}
                                </Text>
                            </span>
                            <Button
                                size="icon-sm"
                                aria-label={`Remove ${event}`}
                                tooltip={`Remove ${event}`}
                                onClick={() => removeTrackedEvent(event)}
                                data-attr="guided-onboarding-events-remove"
                            >
                                <IconX />
                            </Button>
                        </Card>
                    )
                })}
                <div className="flex gap-2">
                    <Input
                        aria-label="Add an event"
                        placeholder={
                            trackedEvents.length
                                ? 'Add another event'
                                : 'Add the first event, for example: profile completed'
                        }
                        value={newEvent}
                        onChange={(event) => setNewEvent(event.target.value)}
                        onKeyDown={(event) => event.key === 'Enter' && add()}
                        data-attr="guided-onboarding-events-new"
                    />
                    <Button
                        variant="outline"
                        onClick={add}
                        disabledReason={!newEvent.trim() ? 'Type an event name first' : undefined}
                        data-attr="guided-onboarding-events-add"
                    >
                        <IconPlus />
                        Add
                    </Button>
                </div>
            </div>
        </StepLayout>
    )
}
