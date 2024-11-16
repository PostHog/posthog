import { AssistantGenerationStatusEvent, AssistantGenerationStatusType } from '~/queries/schema'

import chatResponse from './chatResponse.json'
import failureResponse from './failureResponse.json'

function generateChunk(events: string[]): string {
    return events.map((event) => (event.startsWith('event:') ? `${event}\n` : `${event}\n\n`)).join('')
}

export const chatResponseChunk = generateChunk(['event: message', `data: ${JSON.stringify(chatResponse)}`])

const generationFailure: AssistantGenerationStatusEvent = { type: AssistantGenerationStatusType.GenerationError }
const responseWithReasoningStepsOnly = {
    ...chatResponse,
    answer: null,
}

export const generationFailureChunk = generateChunk([
    'event: message',
    `data: ${JSON.stringify(responseWithReasoningStepsOnly)}`,
    'event: status',
    `data: ${JSON.stringify(generationFailure)}`,
])

export const failureChunk = generateChunk(['event: message', `data: ${JSON.stringify(failureResponse)}`])
