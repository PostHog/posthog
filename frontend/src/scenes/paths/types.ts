import { PathsLink } from '~/queries/schema'

export type PathsNode = { name: string }

export type Paths = {
    nodes: PathsNode[]
    links: PathsLink[]
}
