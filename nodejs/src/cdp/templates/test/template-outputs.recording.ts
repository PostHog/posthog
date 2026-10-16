import { HOG_FUNCTION_TEMPLATES_DESTINATIONS, HOG_FUNCTION_TEMPLATES_TRANSFORMATIONS } from '..'
import { mkdirSync, readFileSync, readdirSync, writeFileSync } from 'fs'
import path from 'path'

import { parseJSON } from '~/common/utils/json-parse'

import { NormalizeContext, normalizeRequests, normalizeValue } from './shadow-recording'
import {
    CorpusEntry,
    INVENTED_CORPUS_PATH,
    PipelineRun,
    QueuedJob,
    TemplateCase,
    TemplatePipeline,
    casesFor,
    loadCorpus,
} from './template-pipeline'

const OUTPUT_DIR = process.env.CDP_TEMPLATE_RECORDING_DIR
const HANDOFF = process.env.CDP_TEMPLATE_HANDOFF
const HANDOFF_DIR = process.env.CDP_TEMPLATE_HANDOFF_DIR
const CORPUS = loadCorpus(process.env.CDP_TEMPLATE_CORPUS || INVENTED_CORPUS_PATH)
const DESTINATION_CASES = casesFor(HOG_FUNCTION_TEMPLATES_DESTINATIONS)
const CASES = [...DESTINATION_CASES, ...casesFor(HOG_FUNCTION_TEMPLATES_TRANSFORMATIONS)]
const FROZEN_NOW = new Date('2025-06-01T12:00:00.000Z')
const OK = { status: 200, body: {} }

type QueuedCase = { corpusEntry: string; inputText: string; job: QueuedJob }[]

const fileNameFor = (templateCase: TemplateCase): string =>
    `${templateCase.name.replace(/[^a-zA-Z0-9-]+/g, '-').toLowerCase()}.json`

const inputTextFor = (templateCase: TemplateCase, entry: CorpusEntry): string =>
    JSON.stringify([entry, templateCase.template])

const recordRun = (
    corpusEntry: string,
    run: PipelineRun,
    context: Omit<NormalizeContext, 'secrets'>
): Record<string, unknown> => {
    const normalizeContext: NormalizeContext = { ...context, secrets: run.secrets }
    const errors = [
        ...run.invocationErrors,
        ...(run.thrown ? [run.thrown] : []),
        ...(run.result?.error ? [String(run.result.error)] : []),
    ]
    return {
        corpusEntry,
        requests: normalizeRequests(run.requests, normalizeContext),
        ...(errors.length ? { errors: errors.map((message) => normalizeValue(message, normalizeContext)) } : {}),
    }
}

const recordTransformationRun = (
    corpusEntry: string,
    run: PipelineRun,
    context: Omit<NormalizeContext, 'secrets'>
): Record<string, unknown> => ({
    ...recordRun(corpusEntry, run, context),
    transformedEvent: normalizeValue(run.result?.execResult ?? null, { ...context, secrets: run.secrets }),
})

const writeJson = (directory: string, fileName: string, value: unknown): void =>
    writeFileSync(path.join(directory, fileName), JSON.stringify(value, null, 2) + '\n')

const requiredDirectory = (directory: string | undefined, variable: string): string => {
    if (!directory) {
        throw new Error(`Set ${variable} to the directory the ${HANDOFF ?? 'recording'} step uses`)
    }
    mkdirSync(directory, { recursive: true })
    return directory
}

describe('template output recording', () => {
    jest.setTimeout(60000)
    let pipeline: TemplatePipeline

    beforeAll(async () => {
        pipeline = await TemplatePipeline.start()
        jest.useFakeTimers({
            now: FROZEN_NOW,
            doNotFake: [
                'nextTick',
                'setImmediate',
                'setInterval',
                'setTimeout',
                'queueMicrotask',
                'clearTimeout',
                'clearInterval',
                'clearImmediate',
                'hrtime',
                'performance',
            ],
        })
    })

    afterAll(async () => {
        jest.useRealTimers()
        await pipeline?.stop()
    })

    if (HANDOFF === 'queue') {
        // Transformations run inline during ingestion, so only destinations pass through the queue.
        it.each(DESTINATION_CASES.map((templateCase) => [templateCase.name, templateCase] as const))(
            'queues %s',
            async (_name, templateCase) => {
                const handoffDir = requiredDirectory(HANDOFF_DIR, 'CDP_TEMPLATE_HANDOFF_DIR')
                const queued: QueuedCase = []
                for (const entry of CORPUS) {
                    const job = await pipeline.queueJob(templateCase, entry)
                    queued.push({ corpusEntry: entry.name, inputText: inputTextFor(templateCase, entry), job })
                }
                writeJson(handoffDir, fileNameFor(templateCase), queued)
            }
        )
    } else if (HANDOFF === 'run') {
        const queuedFiles = HANDOFF_DIR ? readdirSync(HANDOFF_DIR).filter((file) => file.endsWith('.json')) : []

        it('finds queued jobs to run', () => {
            expect(queuedFiles).not.toEqual([])
        })

        it.each(queuedFiles)('runs the jobs queued in %s', async (fileName) => {
            const outputDir = requiredDirectory(OUTPUT_DIR, 'CDP_TEMPLATE_RECORDING_DIR')
            const queued: QueuedCase = parseJSON(readFileSync(path.join(HANDOFF_DIR!, fileName), 'utf-8'))
            const runs = []
            for (const { corpusEntry, inputText, job } of queued) {
                const run = await pipeline.runQueuedJob(job, OK)
                runs.push(recordRun(corpusEntry, run, { inputText, teamId: job.teamId }))
            }
            writeJson(outputDir, fileName, runs)
        })
    } else {
        it.each(CASES.map((templateCase) => [templateCase.name, templateCase] as const))(
            'records %s',
            async (_name, templateCase) => {
                const outputDir = requiredDirectory(OUTPUT_DIR, 'CDP_TEMPLATE_RECORDING_DIR')
                const record = templateCase.template.type === 'transformation' ? recordTransformationRun : recordRun
                const runs = []
                for (const entry of CORPUS) {
                    const run = await pipeline.run(templateCase, OK, { entry })
                    const context = { inputText: inputTextFor(templateCase, entry), teamId: pipeline.teamId }
                    runs.push(record(entry.name, run, context))
                }
                writeJson(outputDir, fileNameFor(templateCase), runs)
            }
        )
    }
})
