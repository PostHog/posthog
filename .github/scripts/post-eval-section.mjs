#!/usr/bin/env node
import fs from 'node:fs'

import { postSection } from '../../frontend/bin/ci-report/update-ci-report.mjs'

const DIFF_THRESHOLD = 0.02

if (!fs.existsSync('eval_results.jsonl')) {
    console.info('No eval_results.jsonl found — nothing to post.')
    process.exit(0)
}

const evalResults = fs
    .readFileSync('eval_results.jsonl', 'utf8')
    .trim()
    .split('\n')
    .filter((line) => line.trim().length > 0)
    .map((line) => JSON.parse(line))

if (evalResults.length === 0) {
    console.info('No eval results found — nothing to post.')
    process.exit(0)
}

const experimentsWithMaxDiff = evalResults.map((result) => {
    const scores = result.scores || {}
    const diffs = Object.values(scores)
        .map((v) => v.diff)
        .filter((d) => typeof d === 'number')
    const minDiff = diffs.length > 0 ? Math.min(...diffs) : 0
    const maxDiff = diffs.length > 0 ? Math.max(...diffs) : 0
    const category = minDiff < -DIFF_THRESHOLD ? 'regression' : maxDiff > DIFF_THRESHOLD ? 'improvement' : 'neutral'

    return {
        result,
        category,
        maxDiffInCategoryAbs:
            category === 'regression'
                ? -minDiff
                : category === 'improvement'
                  ? maxDiff
                  : Math.max(Math.abs(minDiff), Math.abs(maxDiff)),
    }
})

experimentsWithMaxDiff.sort((a, b) => {
    if (a.category === b.category) {
        return b.maxDiffInCategoryAbs - a.maxDiffInCategoryAbs
    }
    const order = { regression: 0, improvement: 1, neutral: 2 }
    return order[a.category] - order[b.category]
})

const experimentSummaries = experimentsWithMaxDiff.map(({ result }) => {
    const scoresList = Object.entries(result.scores || {})
        .map(([key, value]) => {
            const score = typeof value.score === 'number' ? `${(value.score * 100).toFixed(2)}%` : value.score
            let baselineComparison = null
            const diffHighlight = Math.abs(value.diff) > DIFF_THRESHOLD ? '**' : ''
            let diffEmoji = '🆕'
            if (result.comparison_experiment_name?.startsWith('master-')) {
                baselineComparison = `${diffHighlight}${value.diff > 0 ? '+' : value.diff < 0 ? '' : '±'}${(
                    value.diff * 100
                ).toFixed(2)}%${diffHighlight} (improvements: ${value.improvements}, regressions: ${value.regressions})`
                diffEmoji = value.diff > DIFF_THRESHOLD ? '🟢' : value.diff < -DIFF_THRESHOLD ? '🔴' : '🔵'
            }
            return `${diffEmoji} **${key}**: **${score}**${baselineComparison ? `, ${baselineComparison}` : ''}`
        })
        .join('\n')

    const metrics = result.metrics || {}
    const duration = metrics.duration ? `⏱️ ${metrics.duration.metric.toFixed(2)} s` : null
    const totalTokens = metrics.total_tokens ? `🔢 ${Math.floor(metrics.total_tokens.metric)} tokens` : null
    const cost = metrics.estimated_cost ? `💵 $${metrics.estimated_cost.metric.toFixed(4)} in tokens` : null
    const metricsText = [duration, totalTokens, cost].filter(Boolean).join(', ')
    const baselineLink = `[${result.comparison_experiment_name}](${result.project_url}/experiments/${result.comparison_experiment_name})`

    const experimentName = result.project_name.replace(/^max-ai-/, '')

    return [
        `### [${experimentName}](${result.experiment_url})`,
        scoresList,
        `Baseline: ${baselineLink} • Avg. case performance: ${metricsText}`,
    ].join('\n\n')
})

const regressions = []
const improvements = []
const neutral = []
experimentsWithMaxDiff.forEach(({ category }, idx) => {
    if (category === 'regression') {
        regressions.push(experimentSummaries[idx])
    } else if (category === 'improvement') {
        improvements.push(experimentSummaries[idx])
    } else {
        neutral.push(experimentSummaries[idx])
    }
})

const totalExperiments = evalResults.length
const totalMetrics = evalResults.reduce((acc, result) => acc + Object.keys(result.scores || {}).length, 0)

const bodyParts = [
    `Evaluated **${totalExperiments}** experiments, comprising **${totalMetrics}** metrics. Showing experiments with largest regressions first.`,
]

bodyParts.push(...regressions)
bodyParts.push(...improvements)
if (neutral.length > 0) {
    bodyParts.push(
        `<details><summary>${neutral.length} ${neutral.length === 1 ? 'experiment' : 'experiments'} with no significant changes</summary>\n\n${neutral.join('\n\n')}\n\n</details>`
    )
}

const body = bodyParts.join('\n\n')

const status = regressions.length > 0 ? 'warn' : 'ok'
const parts = []
if (regressions.length > 0) {
    parts.push(`${regressions.length} regression${regressions.length === 1 ? '' : 's'}`)
}
if (improvements.length > 0) {
    parts.push(`${improvements.length} improvement${improvements.length === 1 ? '' : 's'}`)
}
const summary = `${totalExperiments} experiment${totalExperiments === 1 ? '' : 's'}${parts.length ? `: ${parts.join(', ')}` : ''}`

await postSection({
    id: 'ai-evals',
    status,
    summary,
    body,
})
