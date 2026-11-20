import { useId } from 'react'

import { Field, FieldLabel, ToggleGroup, ToggleGroupItem } from '@posthog/quill'

export function QuillVisibilityToggleGroup({
    isPrivate,
    onChange,
}: {
    isPrivate: boolean
    onChange: (isPrivate: boolean) => void
}): JSX.Element {
    const id = useId()

    return (
        <Field>
            <FieldLabel htmlFor={id}>Who can use it</FieldLabel>
            <ToggleGroup
                id={id}
                className="w-fit flex-wrap"
                value={[isPrivate ? 'private' : 'project']}
                onValueChange={(next: string[]) => {
                    if (next[0]) {
                        onChange(next[0] === 'private')
                    }
                }}
            >
                <ToggleGroupItem value="private">Only you</ToggleGroupItem>
                <ToggleGroupItem value="project">Everyone in this project</ToggleGroupItem>
            </ToggleGroup>
        </Field>
    )
}
