export function ProjectKeyLabel({ id }: { id: string }): JSX.Element {
    return <span title={id}>Project key · {id.slice(-8)}</span>
}
