// Export for use with actions/github-script

const DIFF_THRESHOLD = 0.01

module.exports = ({ github, context, fs }) => {
    // Read the eval results
    const evalResults = fs
        .readFileSync('eval_results.jsonl', 'utf8')
        .trim()
        .split('\n')
        .map((line) => JSON.parse(line))

    if (evalResults.length === 0) {
        console.warn('No eval results found')
        return
    }

    // Calculate max diff for each experiment and categorize
    const experimentsWithMaxDiff = evalResults.map((result) => {
        const scores = result.scores || {}
        const diffs = Object.values(scores)
            .map((v) => v.diff)
            .filter((d) => typeof d === 'number')
        const minDiff = diffs.length > 0 ? Math.min(...diffs) : 0
        const maxDiff = diffs.length > 0 ? Math.max(...diffs) : 0

        return {
            result,
            maxAbsDiff: Math.max(Math.abs(minDiff), Math.abs(maxDiff)),
            category: minDiff < -DIFF_THRESHOLD ? 'regresion' : maxDiff > DIFF_THRESHOLD ? 'improvement' : 'neutral',
        }
    })

    // Sort: regressions first (most negative to least), then improvements (most positive to least), then neutral
    experimentsWithMaxDiff.sort((a, b) => {
        if (a.category === b.category) {
            return b.maxAbsDiff - a.maxAbsDiff
        }
        const order = { regression: 0, improvement: 1, neutral: 2 }
        return order[a.category] - order[b.category]
    })

    // Generate experiment summaries
    const experimentSummaries = experimentsWithMaxDiff.map(({ result }) => {
        // Format scores as bullet points with improvements/regressions and baseline comparison
        const scoresList = Object.entries(result.scores || {})
            .map(([key, value]) => {
                const score = typeof value.score === 'number' ? `${(value.score * 100).toFixed(2)}%` : value.score
                let baselineComparison = null
                const diffHighlight = Math.abs(value.diff) > DIFF_THRESHOLD ? '**' : ''
                let diffEmoji = '🆕'
                if (result.comparison_experiment_name?.startsWith('master-')) {
                    baselineComparison = `${diffHighlight}${value.diff > 0 ? '+' : value.diff < 0 ? '' : '±'}${(
                        value.diff * 100
                    ).toFixed(
                        2
                    )}%${diffHighlight} (improvements: ${value.improvements}, regressions: ${value.regressions})`
                    diffEmoji = value.diff > DIFF_THRESHOLD ? '🟢' : value.diff < -DIFF_THRESHOLD ? '🔴' : '🔵'
                }
                return `${diffEmoji} **${key}**: **${score}**${baselineComparison ? `, ${baselineComparison}` : ''}`
            })
            .join('\n')

        // Format key metrics concisely
        const metrics = result.metrics || {}
        const duration = metrics.duration ? `⏱️ ${metrics.duration.metric.toFixed(2)} s` : null
        const totalTokens = metrics.total_tokens ? `🔢 ${Math.floor(metrics.total_tokens.metric)} tokens` : null
        const cost = metrics.estimated_cost ? `💵 $${metrics.estimated_cost.metric.toFixed(4)} in tokens` : null
        const metricsText = [duration, totalTokens, cost].filter(Boolean).join(', ')
        const baselineLink = `[${result.comparison_experiment_name}](${result.project_url}/experiments/${result.comparison_experiment_name})`

        // Create concise experiment summary with header only showing experiment name
        const experimentName = result.project_name.replace(/^max-ai-/, '')

        return [
            `### [${experimentName}](${result.experiment_url})`,
            scoresList,
            `Baseline: ${baselineLink} • Avg. case performance: ${metricsText}`,
        ].join('\n\n')
    })

    // Split summaries by category
    const regressions = []
    const improvements = []
    const neutral = []
    experimentsWithMaxDiff.forEach(({ category }, idx) => {
        if (category === 'regression') regressions.push(experimentSummaries[idx])
        else if (category === 'improvement') improvements.push(experimentSummaries[idx])
        else neutral.push(experimentSummaries[idx])
    })

    const totalExperiments = evalResults.length
    const totalMetrics = evalResults.reduce((acc, result) => acc + Object.keys(result.scores || {}).length, 0)

    const bodyParts = [
        `## 🧠 AI eval results`,
        `Evaluated **${totalExperiments}** experiments, comprising **${totalMetrics}** metrics. Showing experiments with largest regressions first.`,
    ]

    bodyParts.push(...regressions)
    bodyParts.push(...improvements)
    if (neutral.length > 0) {
        bodyParts.push(
            `<details><summary>${neutral.length} ${neutral.length === 1 ? 'experiment' : 'experiments'} with no significant changes</summary>\n\n${neutral.join('\n\n')}\n\n</details>`
        )
    }

    bodyParts.push(
        `_Triggered by [this commit](https://github.com/${context.repo.owner}/${context.repo.repo}/pull/${context.payload.pull_request.number}/commits/${context.payload.pull_request.head.sha})._`
    )

    const body = bodyParts.join('\n\n')

    // Post comment on PR
    if (context.payload.pull_request) {
        github.rest.issues.createComment({
            issue_number: context.issue.number,
            owner: context.repo.owner,
            repo: context.repo.repo,
            body: body,
        })
    } else {
        // Just log the summary if this is a push to master
        console.info(body)
    }
}
