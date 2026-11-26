import { ComboboxEmpty, Spinner } from '@posthog/quill'

export function QuillMembersComboboxEmpty({ loading }: { loading: boolean }): JSX.Element {
    return (
        <ComboboxEmpty>
            {loading ? (
                <span className="flex items-center gap-2">
                    <Spinner />
                    Loading members…
                </span>
            ) : (
                'No matching members'
            )}
        </ComboboxEmpty>
    )
}
