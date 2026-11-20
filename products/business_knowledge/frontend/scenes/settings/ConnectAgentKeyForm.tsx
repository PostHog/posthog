import { useActions, useValues } from 'kea'

import { LemonButton, LemonInput, LemonSelect, LemonSkeleton, Link } from '@posthog/lemon-ui'
import {
    Button,
    Input,
    Select,
    SelectContent,
    SelectGroup,
    SelectGroupLabel,
    SelectItem,
    SelectSeparator,
    SelectTrigger,
    SelectValue,
    Skeleton,
    Text,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { useQuillSurface } from 'lib/ui/QuillSurface/quillSurfaceContext'
import { urls } from 'scenes/urls'

import { ALL_KNOWLEDGE, MAX_KEY_LABEL_LENGTH, connectAgentLogic } from './connectAgentLogic'
import { QuillRetryText } from './QuillRetryText'

const ALL_KNOWLEDGE_LABEL = 'All business knowledge'

export function ConnectAgentKeyForm(): JSX.Element {
    const { libraries, librariesLoading, reads, label, creating, createDisabledReason, fixedLibraryId } =
        useValues(connectAgentLogic)
    const { loadLibraries, setReads, setLabel, createKey } = useActions(connectAgentLogic)
    const todayRailNav = useQuillSurface()

    if (!fixedLibraryId && !libraries && todayRailNav) {
        return librariesLoading ? (
            <Skeleton className="h-10 w-full" />
        ) : (
            <QuillRetryText message="Couldn't load your libraries." onRetry={() => loadLibraries()} />
        )
    }
    if (!fixedLibraryId && !libraries) {
        return librariesLoading ? (
            <LemonSkeleton className="h-10 w-full" />
        ) : (
            <p className="m-0">
                Couldn't load your libraries. <Link onClick={() => loadLibraries()}>Try again</Link>
            </p>
        )
    }

    if (todayRailNav) {
        return (
            <div className="flex flex-col gap-2">
                <div className="flex flex-wrap items-center gap-2">
                    {!fixedLibraryId && (
                        <Select value={reads} onValueChange={(value) => setReads(value as string | null)}>
                            <SelectTrigger
                                aria-label="What the agent can read"
                                data-attr="business-knowledge-connect-agent-library"
                            >
                                <SelectValue>
                                    {(value: string | null) =>
                                        value === ALL_KNOWLEDGE
                                            ? ALL_KNOWLEDGE_LABEL
                                            : value
                                              ? ((libraries ?? []).find((library) => library.id === value)?.name ??
                                                value)
                                              : 'Choose what the agent can read'
                                    }
                                </SelectValue>
                            </SelectTrigger>
                            <SelectContent>
                                <SelectItem value={ALL_KNOWLEDGE}>{ALL_KNOWLEDGE_LABEL}</SelectItem>
                                {!!libraries?.length && (
                                    <>
                                        <SelectSeparator />
                                        <SelectGroup>
                                            <SelectGroupLabel>One library</SelectGroupLabel>
                                            {libraries.map((library) => (
                                                <SelectItem key={library.id} value={library.id}>
                                                    {library.name}
                                                </SelectItem>
                                            ))}
                                        </SelectGroup>
                                    </>
                                )}
                            </SelectContent>
                        </Select>
                    )}
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
                {!fixedLibraryId && (
                    <Text size="xs" variant="muted" render={<p className="m-0" />}>
                        {libraries?.length === 0 ? (
                            <>
                                To limit a key to part of your business knowledge,{' '}
                                <Button
                                    variant="link"
                                    size="inline"
                                    nativeButton={false}
                                    render={<LinkPrimitive to={urls.businessKnowledgeLibraries()} />}
                                >
                                    create a library
                                </Button>{' '}
                                and add sources to it.
                            </>
                        ) : (
                            'A key for one library reads only the sources and repositories in that library.'
                        )}
                    </Text>
                )}
            </div>
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
                            { options: [{ value: ALL_KNOWLEDGE, label: ALL_KNOWLEDGE_LABEL }] },
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
