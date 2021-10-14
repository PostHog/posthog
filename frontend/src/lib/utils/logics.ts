import { TeamType } from '../../types'
export interface ProjectBasedLogicProps {
    teamId: TeamType['id'] | null
}

export type LogicKeyBuilder<P extends ProjectBasedLogicProps> = (props: P) => string | number

export function getProjectBasedLogicKeyBuilder<P extends ProjectBasedLogicProps>(
    baseBuilder?: LogicKeyBuilder<P>
): LogicKeyBuilder<P> {
    return (props) => {
        if (!('teamId' in props)) {
            throw new Error("A project-based logic can't be used without an explicitly provided teamId (even null)!")
        }
        return props.teamId
            ? baseBuilder
                ? `${props.teamId}-${baseBuilder(props)}`
                : props.teamId.toString()
            : 'null-team'
    }
}
