import { PathsLink } from '~/queries/schema/schema-general'

export type PathsNode = { name: string }

export type Paths = {
    nodes: PathsNode[]
    links: PathsLink[]
}
