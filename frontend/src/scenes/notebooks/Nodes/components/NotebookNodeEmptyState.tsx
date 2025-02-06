type NotebookNodeEmptyStateProps = {
    message: string
}

export function NotebookNodeEmptyState({ message }: NotebookNodeEmptyStateProps): JSX.Element {
    return (
        <div className="w-full h-full flex flex-col items-center justify-center text-muted p-3">
            <i>{message}</i>
        </div>
    )
}
