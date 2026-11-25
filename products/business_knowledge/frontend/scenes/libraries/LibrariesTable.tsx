import { useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { LemonTable, LemonTag, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { type LibraryTableRow, librariesLogic } from './librariesLogic'

// pinned: setting id from the settings map.
const CONNECT_AGENT_SETTING_URL = combineUrl(
    urls.businessKnowledgeSettings(),
    {},
    { selectedSetting: 'business-knowledge-connect-agent' }
).url

export function LibrariesTable(): JSX.Element {
    const { rows, librariesLoading, keys } = useValues(librariesLogic)

    return (
        <LemonTable<LibraryTableRow>
            dataSource={rows}
            loading={librariesLoading}
            rowKey="id"
            nouns={['library', 'libraries']}
            emptyState="No libraries yet. Create one to give an agent part of your business knowledge."
            columns={[
                {
                    title: 'Name',
                    key: 'name',
                    render: (_, row) => (
                        <span className="flex min-w-0 items-center gap-1">
                            <Link
                                to={row.library ? urls.businessKnowledgeLibrary(row.id) : urls.businessKnowledge()}
                                className="truncate font-semibold"
                                data-attr="business-knowledge-library-open"
                            >
                                {row.name}
                            </Link>
                            {row.library?.is_default && (
                                <LemonTag
                                    type="highlight"
                                    title="Sources learned from support tickets join this library."
                                >
                                    Default
                                </LemonTag>
                            )}
                        </span>
                    ),
                },
                {
                    title: 'Sources',
                    key: 'sources',
                    render: (_, row) => (row.library ? row.library.source_count.toLocaleString() : 'All'),
                },
                {
                    title: 'Repositories',
                    key: 'repositories',
                    render: (_, row) => (row.library ? row.library.repos.length.toLocaleString() : 'All selected'),
                },
                ...(keys
                    ? [
                          {
                              title: 'Agent keys',
                              key: 'keys',
                              tooltip: 'Keys an agent uses to read this library through the PostHog MCP server.',
                              render: (_: unknown, row: LibraryTableRow) =>
                                  row.library ? (
                                      (row.keyCount ?? 0).toLocaleString()
                                  ) : (
                                      <Link to={CONNECT_AGENT_SETTING_URL}>{(row.keyCount ?? 0).toLocaleString()}</Link>
                                  ),
                          },
                      ]
                    : []),
            ]}
        />
    )
}
