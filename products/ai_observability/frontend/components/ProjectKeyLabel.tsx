export function projectKeyDisplayName(id: string): string {
    return `Project key · ${id.slice(-8)}`
}

export function ProjectKeyLabel({ id }: { id: string }): JSX.Element {
    return <span title={id}>{projectKeyDisplayName(id)}</span>
}
