import * as latestVersions from './latest-versions.json'
import { NodeKind } from './schema'
import { integer } from './schema/type-utils'

export const LATEST_VERSIONS = latestVersions as Record<NodeKind, integer>
