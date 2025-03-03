import { PathsV2Item } from '~/queries/schema/schema-general'

export type PathsNode = { name: string }

export type Paths = {
    nodes: PathsNode[]
    links: PathsV2Item[]
}
