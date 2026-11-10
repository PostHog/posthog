import { IngestionOutput } from '~/common/outputs/ingestion-output'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { IngestionOutputMessage } from '~/common/outputs/types'
import { parseJSON } from '~/common/utils/json-parse'

export interface RecordingIngestionOutputs<O extends string> {
    outputs: IngestionOutputs<O>
    produced(output: O): any[]
}

export function createRecordingIngestionOutputs<O extends string>(names: O[]): RecordingIngestionOutputs<O> {
    const messages = new Map<O, IngestionOutputMessage[]>(names.map((name) => [name, []]))
    const recorder = (name: O): IngestionOutput => ({
        produce: (message) => {
            messages.get(name)!.push(message)
            return Promise.resolve()
        },
        queueMessages: (queued) => {
            messages.get(name)!.push(...queued)
            return Promise.resolve()
        },
        checkHealth: () => Promise.resolve(),
        checkTopicExists: () => Promise.resolve(),
    })
    const outputs = new IngestionOutputs(
        Object.fromEntries(names.map((name) => [name, recorder(name)])) as Record<O, IngestionOutput>
    )
    return {
        outputs,
        produced: (output) => messages.get(output)!.map((message) => parseJSON(message.value!.toString())),
    }
}
