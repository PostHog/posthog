type NotebookNodeEmptyStateProps = {
    message: string
}

export function NotebookNodeEmptyState({ message }: NotebookNodeEmptyStateProps): JSX.Element {
    return (
        <div className="text-secondary flex h-full w-full flex-col items-center justify-center p-3">
            <i>{message}</i>
        </div>
    )
}
