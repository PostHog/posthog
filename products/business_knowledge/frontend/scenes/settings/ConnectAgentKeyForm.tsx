import { useActions, useValues } from 'kea'

import { LemonButton, LemonInput, LemonSelect, LemonSkeleton, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { MAX_KEY_LABEL_LENGTH, connectAgentLogic } from './connectAgentLogic'

export function ConnectAgentKeyForm(): JSX.Element {
    const { libraries, librariesLoading, libraryId, label, creating, createDisabledReason } =
        useValues(connectAgentLogic)
    const { loadLibraries, setLibraryId, setLabel, createKey } = useActions(connectAgentLogic)

    if (!libraries) {
        return librariesLoading ? (
            <LemonSkeleton className="h-10 w-full" />
        ) : (
            <p className="m-0">
                Couldn't load your libraries. <Link onClick={() => loadLibraries()}>Try again</Link>
            </p>
        )
    }
    if (libraries.length === 0) {
        return (
            <p className="m-0">
                A key reads one library. <Link to={urls.businessKnowledge()}>Create a library</Link> and add sources to
                it, then come back here.
            </p>
        )
    }

    return (
        <div className="flex flex-wrap items-center gap-2">
            <LemonSelect
                size="small"
                placeholder="Choose a library"
                value={libraryId}
                onChange={setLibraryId}
                options={libraries.map((library) => ({ value: library.id, label: library.name }))}
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
