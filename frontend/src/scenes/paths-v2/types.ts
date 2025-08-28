import { PathsLink } from '~/queries/schema/schema-general'

export enum PathNodeType {
    // regular node
    Node = 'node',
    // dropoffs from previous step
    Dropoff = 'dropoff',
    // aggregate node for the nodes exceeding the row-per-step-limit
    Other = 'other',
}

export type PathsNode = { name: string; type: PathNodeType; step_index: number }

export type Paths = {
    nodes: PathsNode[]
    links: Omit<PathsLink, 'average_conversion_time'>[]
}
