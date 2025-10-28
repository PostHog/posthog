// Export for use with actions/github-script
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
        const maxAbsDiff = diffs.length > 0 ? Math.max(...diffs.map(Math.abs)) : 0
        const maxDiff = diffs.find((d) => Math.abs(d) === maxAbsDiff) || 0

        let category = 'neutral'
        if (result.comparison_experiment_name?.startsWith('master-')) {
            if (maxDiff < -0.01) {
                category = 'regression'
            } else if (maxDiff > 0.01) {
                category = 'improvement'
            }
        }

        return { result, maxDiff, category }
    })

    // Sort: regressions first (most negative to least), then improvements (most positive to least), then neutral
    experimentsWithMaxDiff.sort((a, b) => {
        if (a.category === b.category) {
            if (a.category === 'regression') return a.maxDiff - b.maxDiff // most negative first
            if (a.category === 'improvement') return b.maxDiff - a.maxDiff // most positive first
            return 0
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
                const diffHighlight = Math.abs(value.diff) > 0.01 ? '**' : ''
                let diffEmoji = '🆕'
                if (result.comparison_experiment_name?.startsWith('master-')) {
                    baselineComparison = `${diffHighlight}${value.diff > 0 ? '+' : value.diff < 0 ? '' : '±'}${(
                        value.diff * 100
                    ).toFixed(
                        2
                    )}%${diffHighlight} (improvements: ${value.improvements}, regressions: ${value.regressions})`
                    diffEmoji = value.diff > 0.01 ? '🟢' : value.diff < -0.01 ? '🔴' : '🔵'
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
        `Evaluated **${totalExperiments}** experiments, comprising **${totalMetrics}** metrics.`,
    ]

    bodyParts.push(...regressions)
    bodyParts.push(...improvements)
    if (neutral.length > 0) {
        bodyParts.push(
            `<details><summary>No significant changes (${neutral.length} ${neutral.length === 1 ? 'experiment' : 'experiments'})</summary>\n\n${neutral.join('\n\n')}\n\n</details>`
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
