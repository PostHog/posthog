import { AssistantGenerationStatusEvent, AssistantGenerationStatusType } from '~/queries/schema'

import failureMessage from './failureMessage.json'
import summaryMessage from './summaryMessage.json'
import visualizationMessage from './visualizationMessage.json'

function generateChunk(events: string[]): string {
    return events.map((event) => (event.startsWith('event:') ? `${event}\n` : `${event}\n\n`)).join('')
}

export const chatResponseChunk = generateChunk([
    'event: message',
    `data: ${JSON.stringify(visualizationMessage)}`,
    'event: message',
    `data: ${JSON.stringify(summaryMessage)}`,
])

const generationFailure: AssistantGenerationStatusEvent = { type: AssistantGenerationStatusType.GenerationError }
const responseWithReasoningStepsOnly = {
    ...visualizationMessage,
    answer: null,
}

export const generationFailureChunk = generateChunk([
    'event: message',
    `data: ${JSON.stringify(responseWithReasoningStepsOnly)}`,
    'event: status',
    `data: ${JSON.stringify(generationFailure)}`,
])

export const failureChunk = generateChunk(['event: message', `data: ${JSON.stringify(failureMessage)}`])
