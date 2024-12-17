import {
    AssistantGenerationStatusEvent,
    AssistantGenerationStatusType,
    AssistantMessageType,
    ReasoningMessage,
} from '~/queries/schema'

import failureMessage from './failureMessage.json'
import summaryMessage from './summaryMessage.json'
import visualizationMessage from './visualizationMessage.json'

const reasoningMessage1: ReasoningMessage = {
    type: AssistantMessageType.Reasoning,
    content: 'Picking relevant events and properties',
    done: true,
}

const reasoningMessage2: ReasoningMessage = {
    type: AssistantMessageType.Reasoning,
    content: 'Generating trends',
    done: true,
}

function generateChunk(events: string[]): string {
    return events.map((event) => (event.startsWith('event:') ? `${event}\n` : `${event}\n\n`)).join('')
}

export const chatResponseChunk = generateChunk([
    'event: message',
    `data: ${JSON.stringify(reasoningMessage1)}`,
    'event: message',
    `data: ${JSON.stringify(reasoningMessage2)}`,
    'event: message',
    `data: ${JSON.stringify(visualizationMessage)}`,
    'event: message',
    `data: ${JSON.stringify(summaryMessage)}`,
])

export const chatMidwayResponseChunk = generateChunk([
    'event: message',
    `data: ${JSON.stringify(reasoningMessage1)}`,
    'event: message',
    `data: ${JSON.stringify(reasoningMessage2)}`,
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
