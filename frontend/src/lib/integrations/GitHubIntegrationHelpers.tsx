import { useActions, useValues } from 'kea'
import { useEffect, useMemo } from 'react'

import {
    IconC,
    IconCode,
    IconCPlusPlus,
    IconCSharp,
    IconDart,
    IconElixir,
    IconFlutter,
    IconGitBranch,
    IconGo,
    IconJava,
    IconJavascript,
    IconKotlin,
    IconLock,
    IconPHP,
    IconPython,
    IconReact,
    IconRuby,
    IconRust,
    IconSwift,
} from '@posthog/icons'
import { LemonInputSelect, LemonInputSelectOption, LemonTag } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { LemonField } from 'lib/lemon-ui/LemonField'

import type { GitHubRepoApi } from 'products/integrations/frontend/generated/api.schemas'

import { githubIntegrationLogic } from './githubIntegrationLogic'

export type GitHubRepositoryPickerProps = {
    integrationId: number
    value: string
    onChange: (value: string) => void
    className?: string
}

export const GitHubRepositoryPicker = ({
    value,
    onChange,
    integrationId,
    className,
}: GitHubRepositoryPickerProps): JSX.Element => {
    const { options, loading } = useRepositories(integrationId)

    return (
        <LemonInputSelect
            onChange={(val) => onChange?.(val[0] ?? null)}
            value={value ? [value] : []}
            mode="single"
            data-attr="select-github-repository"
            placeholder="Select a repository..."
            options={options}
            loading={loading}
            className={className}
        />
    )
}

export const GitHubRepositorySelectField = ({ integrationId }: { integrationId: number }): JSX.Element => {
    const { options, loading } = useRepositories(integrationId)

    return (
        <LemonField name="repositories" label="Repository">
            <LemonInputSelect
                mode="single"
                data-attr="select-github-repository"
                placeholder="Select a repository..."
                options={options}
                loading={loading}
            />
        </LemonField>
    )
}

// Epoch ms for sorting; repos cached before pushed_at existed (or with a bad value) sort last.
function pushedAtMs(pushedAt?: string): number {
    const parsed = pushedAt ? Date.parse(pushedAt) : 0
    return Number.isNaN(parsed) ? 0 : parsed
}

// GitHub's primary-language string → its brand icon. Keyed lowercase; TypeScript has no dedicated icon
// so it borrows JavaScript's, and anything unmapped falls back to a generic code glyph.
const LANGUAGE_ICONS: Record<string, typeof IconCode> = {
    python: IconPython,
    javascript: IconJavascript,
    typescript: IconJavascript,
    java: IconJava,
    kotlin: IconKotlin,
    swift: IconSwift,
    ruby: IconRuby,
    rust: IconRust,
    go: IconGo,
    php: IconPHP,
    'c#': IconCSharp,
    'c++': IconCPlusPlus,
    c: IconC,
    dart: IconDart,
    elixir: IconElixir,
    react: IconReact,
    flutter: IconFlutter,
}

// The dropdown row: owner/repo plus the metadata that helps the user pick the right one and know it'll
// work — language, default branch, recency, private/archived, and whether we can actually open PRs there.
function RepoOptionLabel({ repo }: { repo: GitHubRepoApi }): JSX.Element {
    const meta: JSX.Element[] = []
    if (repo.language) {
        const LanguageIcon = LANGUAGE_ICONS[repo.language.toLowerCase()] ?? IconCode
        meta.push(
            <span key="language" className="flex items-center gap-0.5">
                <LanguageIcon />
                {repo.language}
            </span>
        )
    }
    if (repo.default_branch) {
        meta.push(
            <span key="branch" className="flex items-center gap-0.5">
                <IconGitBranch />
                {repo.default_branch}
            </span>
        )
    }
    if (repo.pushed_at) {
        meta.push(<span key="pushed">Updated {dayjs(repo.pushed_at).fromNow()}</span>)
    }
    if (repo.can_push === false) {
        meta.push(
            <span key="no-write" className="text-warning">
                No write access
            </span>
        )
    }

    return (
        <div className="flex flex-col gap-0.5 py-0.5 min-w-0">
            <div className="flex items-center gap-1.5 min-w-0">
                <span className="truncate">{repo.full_name}</span>
                {repo.private && <IconLock className="shrink-0 text-muted" />}
                {repo.archived && (
                    <LemonTag size="small" type="muted">
                        Archived
                    </LemonTag>
                )}
            </div>
            {meta.length > 0 && (
                <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-muted">{meta}</div>
            )}
        </div>
    )
}

export function useRepositories(integrationId: number): { options: LemonInputSelectOption[]; loading: boolean } {
    const logic = githubIntegrationLogic({ id: integrationId })
    const { repositories, repositoriesLoading } = useValues(logic)
    const { loadRepositories } = useActions(logic)

    useEffect(() => {
        loadRepositories()
    }, [loadRepositories])

    const options = useMemo(
        () =>
            // Most-recently-pushed first so the repo the user is working in floats to the top.
            [...repositories]
                .sort((a, b) => pushedAtMs(b.pushed_at) - pushedAtMs(a.pushed_at))
                .map((r) => ({ key: r.name, label: r.full_name, labelComponent: <RepoOptionLabel repo={r} /> })),
        [repositories]
    )

    return { options, loading: repositoriesLoading }
}
