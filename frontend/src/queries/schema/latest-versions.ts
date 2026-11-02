import * as latestVersions from './latest-versions.json'
import { NodeKind } from './schema-general'
import { integer } from './type-utils'

// strip comment
const sanitizedVersions = Object.fromEntries(Object.entries(latestVersions).filter(([key]) => key !== '//'))

export const LATEST_VERSIONS = sanitizedVersions as Record<NodeKind, integer>
