#!/usr/bin/env node
import fs from 'node:fs'
import { pathToFileURL } from 'node:url'

import { postSection } from '../../frontend/bin/ci-report/update-ci-report.mjs'

const DIFF_THRESHOLD = 0.02

// Braintrust always diffs an experiment against some earlier one, and on a PR branch that is
// often an earlier run of the same branch. Only a `master-` baseline says whether this PR
// changed behavior, so a diff against anything else is branch-to-branch noise, which for a
// non-deterministic LLM eval means it must not be counted as a regression.
function hasMasterBaseline(result) {
    return Boolean(result.comparison_experiment_name?.startsWith('master-'))
}

function categorizeExperiment(result) {
    if (!hasMasterBaseline(result)) {
        return { category: 'neutral', maxDiffInCategoryAbs: 0 }
    }

    const diffs = Object.values(result.scores || {})
        .map((value) => value.diff)
        .filter((diff) => typeof diff === 'number')
    const minDiff = diffs.length > 0 ? Math.min(...diffs) : 0
    const maxDiff = diffs.length > 0 ? Math.max(...diffs) : 0
    const category = minDiff < -DIFF_THRESHOLD ? 'regression' : maxDiff > DIFF_THRESHOLD ? 'improvement' : 'neutral'

    return {
        category,
        maxDiffInCategoryAbs:
            category === 'regression'
                ? -minDiff
                : category === 'improvement'
                  ? maxDiff
                  : Math.max(Math.abs(minDiff), Math.abs(maxDiff)),
    }
}

function renderExperiment(result) {
    const comparedToMaster = hasMasterBaseline(result)

    const scoresList = Object.entries(result.scores || {})
        .map(([key, value]) => {
            const score = typeof value.score === 'number' ? `${(value.score * 100).toFixed(2)}%` : value.score
            let baselineComparison = null
            let diffEmoji = '🆕'
            if (comparedToMaster) {
                const diffHighlight = Math.abs(value.diff) > DIFF_THRESHOLD ? '**' : ''
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

    const footerParts = []
    if (result.comparison_experiment_name) {
        footerParts.push(
            `Baseline: [${result.comparison_experiment_name}](${result.project_url}/experiments/${result.comparison_experiment_name})`
        )
    } else {
        footerParts.push('Baseline: none yet, this is the first run of this experiment')
    }
    if (metricsText) {
        footerParts.push(`Avg. case performance: ${metricsText}`)
    }

    const experimentName = result.project_name.replace(/^max-ai-/, '')

    return [`### [${experimentName}](${result.experiment_url})`, scoresList, footerParts.join(' • ')].join('\n\n')
}

export function buildEvalSection(evalResults) {
    if (evalResults.length === 0) {
        return null
    }

    const experiments = evalResults.map((result) => ({ result, ...categorizeExperiment(result) }))

    experiments.sort((a, b) => {
        if (a.category === b.category) {
            return b.maxDiffInCategoryAbs - a.maxDiffInCategoryAbs
        }
        const order = { regression: 0, improvement: 1, neutral: 2 }
        return order[a.category] - order[b.category]
    })

    const regressions = []
    const improvements = []
    const neutral = []
    for (const experiment of experiments) {
        const rendered = renderExperiment(experiment.result)
        if (experiment.category === 'regression') {
            regressions.push(rendered)
        } else if (experiment.category === 'improvement') {
            improvements.push(rendered)
        } else {
            neutral.push(rendered)
        }
    }

    const totalExperiments = evalResults.length
    const totalMetrics = evalResults.reduce((acc, result) => acc + Object.keys(result.scores || {}).length, 0)
    const comparableCount = evalResults.filter(hasMasterBaseline).length

    const bodyParts = [
        `Evaluated **${totalExperiments}** experiments, comprising **${totalMetrics}** metrics. ${
            comparableCount > 0
                ? 'Showing experiments with largest regressions first.'
                : 'None of them had a master baseline to compare against, so these are scores without a comparison.'
        }`,
    ]

    bodyParts.push(...regressions)
    bodyParts.push(...improvements)
    if (neutral.length > 0) {
        bodyParts.push(
            `<details><summary>${neutral.length} ${neutral.length === 1 ? 'experiment' : 'experiments'} with no significant changes</summary>\n\n${neutral.join('\n\n')}\n\n</details>`
        )
    }

    const parts = []
    if (regressions.length > 0) {
        parts.push(`${regressions.length} regression${regressions.length === 1 ? '' : 's'}`)
    }
    if (improvements.length > 0) {
        parts.push(`${improvements.length} improvement${improvements.length === 1 ? '' : 's'}`)
    }

    return {
        status: regressions.length > 0 ? 'warn' : 'ok',
        // The CI report collapses the section down to this line, so it has to separate
        // "compared against master, nothing moved" from "never compared at all". Both
        // leave `parts` empty, and only the second one means the run proves nothing.
        summary: `${totalExperiments} experiment${totalExperiments === 1 ? '' : 's'}${
            comparableCount === 0 ? ': no master baseline' : parts.length ? `: ${parts.join(', ')}` : ''
        }`,
        body: bodyParts.join('\n\n'),
    }
}

async function main() {
    if (!fs.existsSync('eval_results.jsonl')) {
        console.info('No eval_results.jsonl found, nothing to post.')
        return
    }

    const evalResults = fs
        .readFileSync('eval_results.jsonl', 'utf8')
        .trim()
        .split('\n')
        .filter((line) => line.trim().length > 0)
        .map((line) => JSON.parse(line))

    const section = buildEvalSection(evalResults)
    if (!section) {
        console.info('No eval results found, nothing to post.')
        return
    }

    await postSection({ id: 'ai-evals', ...section })
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
    await main()
}
