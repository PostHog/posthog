import { performance } from 'node:perf_hooks'
import { Counter, Histogram } from 'prom-client'

import { DEFAULT_PATTERN_MAX_INPUT_CHARS, DEFAULT_PATTERN_MAX_OUTPUT_CHARS } from './config'
import { MASK_RULES, computeLogPattern } from './log-pattern-mask'
import type { LogRecord } from './log-record-avro'
import type { PipelineStage } from './pipeline/log-processing-pipeline'

export const logsPatternBodyKindCounter = new Counter({
    name: 'logs_ingestion_pattern_body_kind_total',
    help: 'Log bodies seen by the pattern masking stage, split by parse outcome. The structured-versus-prose split.',
    labelNames: ['kind'],
})

export const logsPatternMaskedLengthHistogram = new Histogram({
    name: 'logs_ingestion_pattern_masked_length_chars',
    help: 'Masked pattern length before output truncation. Picks the output truncation length from data.',
    buckets: [8, 16, 32, 64, 128, 256, 512, 1024, 2048, 4096],
})

export const logsPatternKeySetKeysHistogram = new Histogram({
    name: 'logs_ingestion_pattern_keyset_keys',
    help: 'Top-level key count of message-less JSON objects. Everything above the 32 bucket was capped; validates the key-set cap from data.',
    buckets: [1, 2, 4, 8, 16, 24, 32, 48, 64, 128],
})

export const logsPatternMaskingDurationHistogram = new Histogram({
    name: 'logs_ingestion_pattern_masking_duration_seconds',
    help: 'Per-record pattern masking duration.',
    buckets: [0.000001, 0.000005, 0.00001, 0.00005, 0.0001, 0.0005, 0.001, 0.005, 0.01],
})

export const logsPatternRuleFiredCounter = new Counter({
    name: 'logs_ingestion_pattern_rule_fired_total',
    help: 'Mask rule matches, by rule. Shows whether any rule is dead weight.',
    labelNames: ['rule'],
})

export const logsPatternInputCappedCounter = new Counter({
    name: 'logs_ingestion_pattern_input_capped_total',
    help: 'Log bodies cut at the masking input ceiling. Sizes the long-line problem.',
})

export const logsPatternForcedDecodeCounter = new Counter({
    name: 'logs_ingestion_pattern_forced_decode_total',
    help: 'Batches the pattern masking gate pushed onto a costlier buffer path, by what the batch would have done without the stage.',
    labelNames: ['from'],
})

export const logsPatternStageErrorCounter = new Counter({
    name: 'logs_ingestion_pattern_stage_error_total',
    help: 'Batches where the pattern masking stage threw. The records survive; only these metrics are lost.',
})

const positiveIntOr = (value: number, fallback: number): number =>
    Number.isInteger(value) && value > 0 ? value : fallback

export function makePatternMaskingStage(maxInputChars: number, maxOutputChars: number): PipelineStage {
    const inputCap = positiveIntOr(maxInputChars, DEFAULT_PATTERN_MAX_INPUT_CHARS)
    const outputCap = positiveIntOr(maxOutputChars, DEFAULT_PATTERN_MAX_OUTPUT_CHARS)
    return {
        kind: 'mutate',
        name: 'pattern_masking',
        run: (records) => {
            try {
                measureBatch(records, inputCap, outputCap)
            } catch {
                logsPatternStageErrorCounter.inc()
            }
        },
    }
}

function measureBatch(records: LogRecord[], inputCap: number, outputCap: number): void {
    const kindCounts = new Map<string, number>()
    const ruleFires: number[] = new Array(MASK_RULES.length).fill(0)
    let inputCapped = 0

    for (const record of records) {
        const start = performance.now()
        const result = computeLogPattern(record.body, inputCap, outputCap)
        logsPatternMaskingDurationHistogram.observe((performance.now() - start) / 1000)

        logsPatternMaskedLengthHistogram.observe(result.maskedLength)
        if (result.jsonKeyCount !== undefined) {
            logsPatternKeySetKeysHistogram.observe(result.jsonKeyCount)
        }
        kindCounts.set(result.bodyKind, (kindCounts.get(result.bodyKind) ?? 0) + 1)
        for (let i = 0; i < result.ruleFires.length; i++) {
            ruleFires[i] += result.ruleFires[i]
        }
        if (result.inputCapped) {
            inputCapped++
        }
    }

    for (const [kind, count] of kindCounts) {
        logsPatternBodyKindCounter.inc({ kind }, count)
    }
    for (let i = 0; i < ruleFires.length; i++) {
        if (ruleFires[i] > 0) {
            logsPatternRuleFiredCounter.inc({ rule: MASK_RULES[i].name }, ruleFires[i])
        }
    }
    if (inputCapped > 0) {
        logsPatternInputCappedCounter.inc(inputCapped)
    }
}
