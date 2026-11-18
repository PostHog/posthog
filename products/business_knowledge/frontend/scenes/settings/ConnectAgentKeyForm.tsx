import { useActions, useValues } from 'kea'

import { LemonButton, LemonInput, LemonSelect, LemonSkeleton, Link } from '@posthog/lemon-ui'
import {
    Button,
    Input,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Skeleton,
    Text,
} from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { MAX_KEY_LABEL_LENGTH, connectAgentLogic } from './connectAgentLogic'
import { QuillRetryText } from './QuillRetryText'

export function ConnectAgentKeyForm(): JSX.Element {
    const { libraries, librariesLoading, libraryId, label, creating, createDisabledReason } =
        useValues(connectAgentLogic)
    const { loadLibraries, setLibraryId, setLabel, createKey } = useActions(connectAgentLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (!libraries && todayRailNav) {
        return librariesLoading ? (
            <Skeleton className="h-10 w-full" />
        ) : (
            <QuillRetryText message="Couldn't load your libraries." onRetry={() => loadLibraries()} />
        )
    }
    if (!libraries) {
        return librariesLoading ? (
            <LemonSkeleton className="h-10 w-full" />
        ) : (
            <p className="m-0">
                Couldn't load your libraries. <Link onClick={() => loadLibraries()}>Try again</Link>
            </p>
        )
    }
    if (libraries.length === 0 && todayRailNav) {
        return (
            <Text size="xs" render={<p className="m-0" />}>
                A key reads one library.{' '}
                <Button
                    variant="link"
                    size="inline"
                    nativeButton={false}
                    render={<LinkPrimitive to={urls.businessKnowledge()} />}
                >
                    Create a library
                </Button>{' '}
                and add sources to it, then come back here.
            </Text>
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

    if (todayRailNav) {
        return (
            <div className="flex flex-wrap items-center gap-2">
                <Select value={libraryId} onValueChange={(value) => setLibraryId(value as typeof libraryId)}>
                    <SelectTrigger aria-label="Library" data-attr="business-knowledge-connect-agent-library">
                        <SelectValue>
                            {(value: string | null) =>
                                value
                                    ? (libraries.find((library) => library.id === value)?.name ?? value)
                                    : 'Choose a library'
                            }
                        </SelectValue>
                    </SelectTrigger>
                    <SelectContent>
                        {libraries.map((library) => (
                            <SelectItem key={library.id} value={library.id}>
                                {library.name}
                            </SelectItem>
                        ))}
                    </SelectContent>
                </Select>
                <Input
                    className="w-48"
                    placeholder="Key name"
                    aria-label="Key name"
                    value={label}
                    onChange={(event) => setLabel(event.target.value)}
                    maxLength={MAX_KEY_LABEL_LENGTH}
                    onKeyDown={(event) => {
                        if (event.key === 'Enter' && !createDisabledReason) {
                            createKey()
                        }
                    }}
                    data-attr="business-knowledge-connect-agent-key-name"
                />
                <Button
                    variant="primary"
                    loading={creating}
                    disabledReason={createDisabledReason}
                    onClick={createKey}
                    data-attr="business-knowledge-connect-agent-create-library-key"
                >
                    Create key
                </Button>
            </div>
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
