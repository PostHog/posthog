import { useId } from 'react'

import {
    Combobox,
    ComboboxChip,
    ComboboxChips,
    ComboboxChipsInput,
    ComboboxContent,
    ComboboxEmpty,
    ComboboxItem,
    ComboboxList,
    ComboboxValue,
    Field,
    FieldDescription,
    FieldLabel,
    Spinner,
    useComboboxAnchor,
} from '@posthog/quill'

export function QuillGithubRepoField({
    repoNames,
    loading,
    value,
    disabledReason,
    onChange,
    onOpen,
}: {
    repoNames: string[]
    loading: boolean
    value: string[]
    disabledReason: string | null
    onChange: (repos: string[]) => void
    onOpen: () => void
}): JSX.Element {
    const id = useId()

    return (
        <Field>
            <FieldLabel htmlFor={id}>Monitored repositories</FieldLabel>
            <FieldDescription>
                Select which repositories to watch for new issues. Only issues from these repos will create tickets.
            </FieldDescription>
            <Combobox<string, true>
                multiple
                items={repoNames}
                value={value}
                onValueChange={(next) => onChange(next ?? [])}
                onOpenChange={(open) => {
                    if (open) {
                        onOpen()
                    }
                }}
            >
                <QuillGithubRepoChips id={id} loading={loading} disabledReason={disabledReason} />
            </Combobox>
        </Field>
    )
}

function QuillGithubRepoChips({
    id,
    loading,
    disabledReason,
}: {
    id: string
    loading: boolean
    disabledReason: string | null
}): JSX.Element {
    const anchor = useComboboxAnchor()

    return (
        <>
            <ComboboxChips ref={anchor} disabledReason={disabledReason}>
                <ComboboxValue>
                    {(repos: string[]) => (
                        <>
                            {repos.map((repo) => (
                                <ComboboxChip key={repo}>{repo}</ComboboxChip>
                            ))}
                            <ComboboxChipsInput id={id} placeholder={repos.length ? '' : 'Select repositories...'} />
                        </>
                    )}
                </ComboboxValue>
            </ComboboxChips>
            <ComboboxContent anchor={anchor}>
                <ComboboxEmpty>{loading ? <Spinner /> : 'No matching repositories'}</ComboboxEmpty>
                <ComboboxList>
                    {(repo: string) => (
                        <ComboboxItem key={repo} value={repo}>
                            {repo}
                        </ComboboxItem>
                    )}
                </ComboboxList>
            </ComboboxContent>
        </>
    )
}
