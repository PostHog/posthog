import { kea, path, actions, listeners } from 'kea'
import type { inAppPromptEventCaptureLogicType } from './inAppPromptEventCaptureLogicType'
import posthog from 'posthog-js'
import { PromptType } from './inAppPromptLogic'

const inAppPromptEventCaptureLogic = kea<inAppPromptEventCaptureLogicType>([
    path(['lib', 'logic', 'inAppPrompt', 'eventCapture']),
    actions({
        reportPromptShown: (type: PromptType, sequence: string, step: number, totalSteps: number) => ({
            type,
            sequence,
            step,
            totalSteps,
        }),
        reportPromptForward: (sequence: string, step: number, totalSteps: number) => ({ sequence, step, totalSteps }),
        reportPromptBackward: (sequence: string, step: number, totalSteps: number) => ({ sequence, step, totalSteps }),
        reportPromptSequenceDismissed: (sequence: string, step: number, totalSteps: number) => ({
            sequence,
            step,
            totalSteps,
        }),
        reportPromptSequenceCompleted: (sequence: string, step: number, totalSteps: number) => ({
            sequence,
            step,
            totalSteps,
        }),
        reportTutorialSkipped: true,
    }),
    listeners({
        reportPromptShown: ({ type, sequence, step, totalSteps }) => {
            posthog.capture('prompt shown', {
                type,
                sequence,
                step,
                totalSteps,
            })
        },
        reportPromptForward: ({ sequence, step, totalSteps }) => {
            posthog.capture('prompt forward', {
                sequence,
                step,
                totalSteps,
            })
        },
        reportPromptBackward: ({ sequence, step, totalSteps }) => {
            posthog.capture('prompt backward', {
                sequence,
                step,
                totalSteps,
            })
        },
        reportPromptSequenceDismissed: ({ sequence, step, totalSteps }) => {
            posthog.capture('prompt sequence dismissed', {
                sequence,
                step,
                totalSteps,
            })
        },
        reportPromptSequenceCompleted: ({ sequence, step, totalSteps }) => {
            posthog.capture('prompt sequence completed', {
                sequence,
                step,
                totalSteps,
            })
        },
        reportTutorialSkipped: () => {
            posthog.capture('tutorial skipped')
        },
    }),
])

export { inAppPromptEventCaptureLogic }
