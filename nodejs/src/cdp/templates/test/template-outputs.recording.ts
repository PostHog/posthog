import { HOG_FUNCTION_TEMPLATES_DESTINATIONS, HOG_FUNCTION_TEMPLATES_TRANSFORMATIONS } from '..'
import { mkdirSync, writeFileSync } from 'fs'
import path from 'path'

import { NormalizeContext, normalizeRequests, normalizeValue } from './shadow-recording'
import {
    CorpusEntry,
    INVENTED_CORPUS_PATH,
    PipelineRun,
    TemplateCase,
    TemplatePipeline,
    casesFor,
    loadCorpus,
} from './template-pipeline'

const OUTPUT_DIR = process.env.CDP_TEMPLATE_RECORDING_DIR
const CORPUS = loadCorpus(process.env.CDP_TEMPLATE_CORPUS || INVENTED_CORPUS_PATH)
const CASES = casesFor([...HOG_FUNCTION_TEMPLATES_DESTINATIONS, ...HOG_FUNCTION_TEMPLATES_TRANSFORMATIONS])
const FROZEN_NOW = new Date('2025-06-01T12:00:00.000Z')
const OK = { status: 200, body: {} }

const fileNameFor = (templateCase: TemplateCase): string =>
    `${templateCase.name.replace(/[^a-zA-Z0-9-]+/g, '-').toLowerCase()}.json`

const recordRun = (
    templateCase: TemplateCase,
    entry: CorpusEntry,
    run: PipelineRun,
    teamId: number
): Record<string, unknown> => {
    const context: NormalizeContext = { sensitiveValues: run.sensitiveValues, inputText: JSON.stringify(entry), teamId }
    const errors = [...run.invocationErrors, ...(run.result?.error ? [String(run.result.error)] : [])]
    return {
        corpusEntry: entry.name,
        requests: normalizeRequests(run.requests, context),
        ...(templateCase.template.type === 'transformation'
            ? { transformedEvent: normalizeValue(run.result?.execResult ?? null, context) }
            : {}),
        ...(errors.length ? { errors: errors.map((message) => normalizeValue(message, context)) } : {}),
    }
}

describe('template output recording', () => {
    jest.setTimeout(60000)
    let pipeline: TemplatePipeline

    beforeAll(async () => {
        if (!OUTPUT_DIR) {
            throw new Error('Set CDP_TEMPLATE_RECORDING_DIR to the directory the recording goes to')
        }
        mkdirSync(OUTPUT_DIR, { recursive: true })
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

    it.each(CASES.map((templateCase) => [templateCase.name, templateCase] as const))(
        'records %s',
        async (_name, templateCase) => {
            const runs = []
            for (const entry of CORPUS) {
                const run = await pipeline.run(templateCase, OK, { entry })
                runs.push(recordRun(templateCase, entry, run, pipeline.teamId))
            }
            writeFileSync(path.join(OUTPUT_DIR!, fileNameFor(templateCase)), JSON.stringify(runs, null, 2) + '\n')
        }
    )
})
