import { Empty, EmptyDescription, EmptyHeader } from '@posthog/quill'

export function GovernanceTableEmpty({ children }: { children: string }): JSX.Element {
    return (
        <Empty>
            <EmptyHeader>
                <EmptyDescription>{children}</EmptyDescription>
            </EmptyHeader>
        </Empty>
    )
}
