import { join, relative, sep } from 'node:path'

import type { Context } from '@/core/context'
import { EXIT_USAGE, HogError } from '@/core/errors'
import { escapeControls } from '@/core/output'
import { isInside, realWritePath } from '@/core/paths'
import { resolveStack } from '@/stack/config'

import template from './stack-workflow.yml.txt'

export interface StackWorkflow {
    status: 'workflow'
    path: string
    created: boolean
    approvals: { diff: string }
    reviewEnvironment: string
    scopeHint: string
}

function yamlString(value: string): string {
    if (value.includes('${{') || escapeControls(value) !== value || /[\t\n]/.test(value)) {
        throw new HogError(
            'stack_workflow_value_invalid',
            'GitHub cannot use this folder or host literally in the workflow.',
            'Use a folder and host without GitHub expressions or control characters.',
            EXIT_USAGE
        )
    }
    return JSON.stringify(value)
}

function pattern(path: string): string {
    return path.replace(/[\\*?+[\]!]/g, '\\$&')
}

function quote(value: string): string {
    return `'${value.replaceAll("'", "'\\''")}'`
}

export async function writeStackWorkflow(ctx: Context, name: string, env?: string): Promise<StackWorkflow> {
    const stack = await resolveStack(ctx, name, env)
    const repo = stack.root
    if (!(await ctx.runtime.exists(join(repo, '.git'))) || (stack.path !== repo && !isInside(repo, stack.path))) {
        throw new HogError(
            'stack_workflow_folder_invalid',
            'The stack folder must be inside this Git repository for GitHub to run its diff.',
            'Set the stack folder in posthog.json and run the command from the repository.',
            EXIT_USAGE
        )
    }
    const label = stack.env ? `${name}.${stack.env}` : name
    const reviewEnvironment = `posthog-diff-${label}`
    const path = `.github/workflows/posthog-${label}.yml`
    const destination = join(repo, path)
    const root = await ctx.runtime.realPath(repo)
    if (!isInside(root, await realWritePath(ctx.runtime, destination))) {
        throw new HogError(
            'stack_workflow_folder_invalid',
            'The workflow folder links outside the repository.',
            'Use a .github/workflows folder inside the repository.',
            EXIT_USAGE
        )
    }
    const target = stack.environment ?? (await ctx.session()).current
    const project = String('project' in target ? target.project : target.projectId)
    const folder = relative(repo, stack.path).split(sep).join('/') || '.'
    const configDir = relative(repo, stack.configRoot).split(sep).join('/') || '.'
    const config = configDir === '.' ? 'posthog.json' : `${configDir}/posthog.json`
    const values: Record<string, string> = {
        LABEL: label,
        REVIEWENV: reviewEnvironment,
        OPTIONS: `--stack ${name}${stack.env ? ` --env ${stack.env}` : ''}`,
        DIR: yamlString(folder),
        ROOT: yamlString(configDir),
        PATTERN: yamlString(folder === '.' ? '**' : `${pattern(folder)}/**`),
        CONFIG: yamlString(pattern(config)),
        HOST: yamlString(target.host),
        PROJECT: yamlString(project),
        VERSION: `@${ctx.runtime.build.version}`,
    }
    const contents = template.replace(/@@([A-Z]+)@@/g, (_, key: string) => values[key]!)
    const created = await ctx.runtime.createFile(destination, contents)
    if (!created && (await ctx.runtime.readFile(destination)) !== contents) {
        throw new HogError(
            'stack_workflow_exists',
            `${path} already holds a different workflow.`,
            'Keep your changes by moving the existing file aside, then run the command again and compare the files.',
            EXIT_USAGE
        )
    }
    const setup = `HOG_PROJECT_ID=${project} hog ci setup --host ${quote(target.host)}`
    return {
        status: 'workflow',
        created,
        path,
        reviewEnvironment,
        approvals: {
            diff: `${setup} --preset environment=${reviewEnvironment} --scope stack:read --claim event_name=pull_request`,
        },
        scopeHint:
            'Add the read scopes for the definitions in this stack to the approval command. For dashboards, for example, add --scope dashboard:read,insight:read.',
    }
}
