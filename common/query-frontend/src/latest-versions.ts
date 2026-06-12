import * as latestVersions from './latest-versions.json'
import { NodeKind } from './schema'
import { integer } from './schema/type-utils'

// strip comment
const sanitizedVersions = Object.fromEntries(Object.entries(latestVersions).filter(([key]) => key !== '//'))

export const LATEST_VERSIONS = sanitizedVersions as Record<NodeKind, integer>
