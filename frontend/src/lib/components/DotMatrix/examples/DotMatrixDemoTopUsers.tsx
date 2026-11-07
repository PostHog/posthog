import { type DotMatrixMockPerson } from './dotMatrixMockTypes'

interface DotMatrixDemoTopUsersProps {
    rowKey: string
    activePeopleCount: number
    people: DotMatrixMockPerson[]
}

export function DotMatrixDemoTopUsers({
    rowKey,
    activePeopleCount,
    people,
}: DotMatrixDemoTopUsersProps): JSX.Element | null {
    if (rowKey.startsWith('group:')) {
        return null
    }
    if (rowKey === 'summary') {
        return <span className="DotMatrixDemo__top-users">{`${activePeopleCount} active users`}</span>
    }
    const persons = people
    return (
        <span className="DotMatrixDemo__top-users">
            {persons
                .slice(0, 3)
                .map((person) => person.name)
                .join(', ')}
            {persons.length > 3 ? ` +${persons.length - 3}` : ''}
        </span>
    )
}
