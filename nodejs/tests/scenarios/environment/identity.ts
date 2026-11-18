export type ReplicaOf<R extends string = string> = { role: R; replica: number }

export const nameOf = ({ role, replica }: ReplicaOf): string => (replica === 0 ? role : `${role}-${replica}`)
