import { defineCommand } from '@/core/command'
import { CONFIG_FILE, findConfig, validateConfig, type ConfigProblem } from '@/core/config'

type CheckResult =
    | { status: 'missing'; next: string }
    | { status: 'valid'; path: string }
    | { status: 'invalid'; path: string; problems: ConfigProblem[] }

export default defineCommand({
    description: 'Check posthog.json against its schema and list every problem',
    allowsInvalidConfig: true,
    notes: `hog looks for ${CONFIG_FILE} in the current folder, then in each parent up to the git root. Exits with code 1 when the file is missing or has problems.`,
    examples: ['hog config check'],

    async run({ ctx }): Promise<CheckResult> {
        const path = await findConfig(ctx.runtime)
        if (path === undefined) {
            return { status: 'missing', next: 'hog config schema' }
        }
        const { problems } = validateConfig(await ctx.runtime.readFile(path))
        return problems.length === 0 ? { status: 'valid', path } : { status: 'invalid', path, problems }
    },

    human({ result, out }) {
        if (result.status === 'missing') {
            out.line(out.style(`No ${CONFIG_FILE} between here and the git root.`, 'yellow', 'bold'))
            out.line(`Run ${out.style(result.next, 'bold')} to see what it can hold.`)
            return
        }
        if (result.status === 'valid') {
            out.line(`${out.style('Valid', 'green', 'bold')}: ${result.path}`)
            return
        }
        out.line(`${out.style('Invalid', 'red', 'bold')}: ${result.path}`)
        for (const problem of result.problems) {
            out.line(`  ${out.style(problem.path || '(root)', 'bold')}  ${problem.message}`)
        }
    },

    exitCode: (result) => (result.status === 'valid' ? 0 : 1),
})
