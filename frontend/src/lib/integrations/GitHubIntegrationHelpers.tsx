import { useActions, useValues } from 'kea'
import { useId, useMemo } from 'react'

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
import { LemonInputSelect, LemonInputSelectProps, LemonTag } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { IntegrationType } from '~/types'

import type { GitHubRepoApi } from 'products/integrations/frontend/generated/api.schemas'

import { githubRepositorySearchLogic } from './githubRepositorySearchLogic'

/**
 * The project's GitHub integration for anything that runs on the team's behalf rather than one
 * person's: scheduled work, and settings a whole project shares.
 *
 * Must pick the same one as the backend's `resolve_team_github_integration` (org accounts first,
 * then oldest; broken installs skipped), or a picker built on this offers repositories the
 * server-side validation then rejects.
 */
export function resolveTeamGitHubIntegration(integrations: IntegrationType[]): IntegrationType | undefined {
    return integrations
        .filter(
            (integration) =>
                integration.errors !== 'TOKEN_REFRESH_FAILED' && !integration.config?.installation_unavailable_since
        )
        .sort(
            (a, b) =>
                // Missing account type sorts last, like Postgres NULLS LAST.
                (a.config?.account?.type ?? '\uffff').localeCompare(b.config?.account?.type ?? '\uffff') ||
                a.created_at.localeCompare(b.created_at) ||
                a.id - b.id
        )[0]
}

export type GitHubRepositoryPickerProps = {
    integrationId: number
    /** Selected key. Leave it out for a picker that only adds, so it resets after each pick. */
    value?: string
    /** Receives the selected key and, when it is one of the loaded options, the full repository. */
    onChange: (value: string, repository?: GitHubRepoApi) => void
    className?: string
    /** Which repo field the picker stores and returns. Default 'name' keeps existing callers'
     * stored short names working; 'full_name' is for callers matching a webhook delivery's
     * "owner/repo" property, which carries no owner otherwise. */
    valueKey?: 'name' | 'full_name'
    /** Hides repositories that are not valid choices here, such as ones already added. */
    repositoryFilter?: (repository: GitHubRepoApi) => boolean
    placeholder?: string
    disabledReason?: string
}

export const GitHubRepositoryPicker = ({
    value,
    onChange,
    integrationId,
    className,
    valueKey = 'name',
    repositoryFilter,
    placeholder = 'Select a repository...',
    disabledReason,
}: GitHubRepositoryPickerProps): JSX.Element => {
    const { repositories, selectProps } = useRepositories(integrationId, { valueKey, repositoryFilter })

    return (
        <LemonInputSelect
            {...selectProps}
            onChange={(val) => {
                const key = val[0] ?? null
                onChange?.(
                    key,
                    repositories.find((repository) => repositoryKey(repository, valueKey) === key)
                )
            }}
            value={value ? [value] : []}
            mode="single"
            data-attr="select-github-repository"
            placeholder={placeholder}
            className={className}
            disabledReason={disabledReason}
        />
    )
}

export const GitHubRepositorySelectField = ({ integrationId }: { integrationId: number }): JSX.Element => {
    const { selectProps } = useRepositories(integrationId)

    return (
        <LemonField name="repositories" label="Repository">
            <LemonInputSelect
                {...selectProps}
                mode="single"
                data-attr="select-github-repository"
                placeholder="Select a repository..."
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

// A qualified-name key is lowercased because the stored value is. The API lowercases a repository
// filter on save, while GitHub reports `full_name` in the owner's casing. Compared as-is, the stored
// value matches no option, so LemonInputSelect shows it as a custom value beside the real repository
// and drops the rich label.
function repositoryKey(repository: GitHubRepoApi, valueKey: 'name' | 'full_name'): string {
    return valueKey === 'full_name' ? repository.full_name.toLowerCase() : repository.name
}

interface RepositoryOptions {
    repositories: GitHubRepoApi[]
    searchQuery: string
    /** Spread into a LemonInputSelect so typing searches the installation on the server. */
    selectProps: Required<Pick<LemonInputSelectProps, 'options' | 'loading'>> &
        Pick<LemonInputSelectProps, 'onInputChange' | 'disableFiltering' | 'title' | 'emptyStateComponent'>
}

/** Repository options for one integration, searched on the server so large installations are not cut off. */
export function useRepositories(
    integrationId: number,
    {
        valueKey = 'name',
        repositoryFilter,
    }: { valueKey?: 'name' | 'full_name'; repositoryFilter?: (repository: GitHubRepoApi) => boolean } = {}
): RepositoryOptions {
    // Each picker gets its own search state, so typing in one does not refilter another on the same page.
    const logic = githubRepositorySearchLogic({ id: integrationId, instanceKey: useId() })
    const { repositories, loading, hasMore, searchQuery, error } = useValues(logic)
    const { setSearchQuery } = useActions(logic)

    const options = useMemo(
        () =>
            // Most-recently-pushed first so the repo the user is working in floats to the top.
            repositories
                .filter((r) => !repositoryFilter || repositoryFilter(r))
                .sort((a, b) => pushedAtMs(b.pushed_at) - pushedAtMs(a.pushed_at))
                .map((r) => ({
                    key: repositoryKey(r, valueKey),
                    label: r.full_name,
                    labelComponent: <RepoOptionLabel repo={r} />,
                })),
        [repositories, valueKey, repositoryFilter]
    )

    return {
        repositories,
        searchQuery,
        selectProps: {
            options,
            loading,
            // Skip input changes that leave the search unchanged, such as a trailing space or the clear
            // after a pick when nothing was typed. Each search clears the list and refetches it.
            onInputChange: (query) => query.trim() !== searchQuery.trim() && setSearchQuery(query),
            disableFiltering: true,
            title: hasMore ? 'Type to search all repositories' : undefined,
            emptyStateComponent: error ?? undefined,
        },
    }
}
