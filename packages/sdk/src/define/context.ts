import type { ContextLayerContextWikiPageUpdateInput } from '../generated/api.js'
import { type Definition, defineKind } from './definition.js'
import { markdownFiles } from './files.js'

export type ContextPageBody = Omit<ContextLayerContextWikiPageUpdateInput, 'base_head'>

export type ContextPageDefinition<Path extends string = string> = Definition<'context_page', Path, ContextPageBody>

// One page of the context wiki, keyed by its path, such as `projects/2/metrics.md`.
export function contextPage<const Path extends string>(
    path: Path,
    input: { content: string }
): ContextPageDefinition<Path> {
    return defineKind('context_page', path, { path, content: input.content })
}

// A page for every `.md` file under a folder, relative to the calling file. `prefix` is the wiki
// folder they go in.
export function contextPages(folder: string, { prefix = '' }: { prefix?: string } = {}): ContextPageDefinition[] {
    const base = prefix.replace(/\/+$/, '')
    return markdownFiles(folder).map(({ path, content }) => contextPage(base ? `${base}/${path}` : path, { content }))
}
