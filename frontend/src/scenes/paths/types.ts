import { PathsLink } from '~/schema'

export type PathsNode = { name: string }

export type Paths = {
    nodes: PathsNode[]
    links: PathsLink[]
}
