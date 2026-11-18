import { useActions, useValues } from 'kea'

import { LemonButton, LemonInput, LemonSelect, LemonSkeleton, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { ALL_KNOWLEDGE, MAX_KEY_LABEL_LENGTH, connectAgentLogic } from './connectAgentLogic'

export function ConnectAgentKeyForm(): JSX.Element {
    const { libraries, librariesLoading, reads, label, creating, createDisabledReason } = useValues(connectAgentLogic)
    const { loadLibraries, setReads, setLabel, createKey } = useActions(connectAgentLogic)

    if (!libraries) {
        return librariesLoading ? (
            <LemonSkeleton className="h-10 w-full" />
        ) : (
            <p className="m-0">
                Couldn't load your libraries. <Link onClick={() => loadLibraries()}>Try again</Link>
            </p>
        )
    }

    return (
        <div className="flex flex-wrap items-center gap-2">
            <LemonSelect
                size="small"
                placeholder="Choose what the agent can read"
                value={reads}
                onChange={setReads}
                options={[
                    { options: [{ value: ALL_KNOWLEDGE, label: 'All business knowledge' }] },
                    {
                        title: 'One library',
                        options: libraries.map((library) => ({ value: library.id, label: library.name })),
                        footer:
                            libraries.length === 0 ? (
                                <div className="px-2 py-1 text-xs text-secondary">
                                    <Link to={urls.businessKnowledge()}>Create a library</Link> to limit a key to it.
                                </div>
                            ) : undefined,
                    },
                ]}
                // pinned: data-attr value. Autocapture insights and tests select on it.
                data-attr="business-knowledge-connect-agent-library"
            />
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
    )
}
