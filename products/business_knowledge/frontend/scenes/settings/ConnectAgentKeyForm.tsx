import { useActions, useValues } from 'kea'

import { LemonButton, LemonInput, LemonSelect, LemonSkeleton, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { ALL_KNOWLEDGE, MAX_KEY_LABEL_LENGTH, connectAgentLogic } from './connectAgentLogic'

export function ConnectAgentKeyForm(): JSX.Element {
    const { libraries, librariesLoading, reads, label, creating, createDisabledReason, fixedLibraryId } =
        useValues(connectAgentLogic)
    const { loadLibraries, setReads, setLabel, createKey } = useActions(connectAgentLogic)

    if (!fixedLibraryId && !libraries) {
        return librariesLoading ? (
            <LemonSkeleton className="h-10 w-full" />
        ) : (
            <p className="m-0">
                Couldn't load your libraries. <Link onClick={() => loadLibraries()}>Try again</Link>
            </p>
        )
    }

    return (
        <div className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center gap-2">
                {!fixedLibraryId && (
                    <LemonSelect
                        size="small"
                        placeholder="Choose what the agent can read"
                        value={reads}
                        onChange={setReads}
                        options={[
                            { options: [{ value: ALL_KNOWLEDGE, label: 'All business knowledge' }] },
                            {
                                title: 'One library',
                                options: (libraries ?? []).map((library) => ({
                                    value: library.id,
                                    label: library.name,
                                })),
                            },
                        ]}
                        data-attr="business-knowledge-connect-agent-library"
                    />
                )}
                <LemonInput
                    size="small"
                    className="w-48"
                    placeholder="Key name"
                    value={label}
                    onChange={setLabel}
                    maxLength={MAX_KEY_LABEL_LENGTH}
                    onPressEnter={createDisabledReason ? undefined : createKey}
                    data-attr="business-knowledge-connect-agent-key-name"
                />
                <LemonButton
                    type="primary"
                    size="small"
                    loading={creating}
                    disabledReason={createDisabledReason}
                    onClick={createKey}
                    data-attr="business-knowledge-connect-agent-create-library-key"
                >
                    Create key
                </LemonButton>
            </div>
            {!fixedLibraryId && (
                <span className="text-xs text-secondary">
                    {libraries?.length === 0 ? (
                        <>
                            To limit a key to part of your business knowledge,{' '}
                            <Link to={urls.businessKnowledgeLibraries()}>create a library</Link> and add sources to it.
                        </>
                    ) : (
                        'A key for one library reads only the sources and repositories in that library.'
                    )}
                </span>
            )}
        </div>
    )
}
